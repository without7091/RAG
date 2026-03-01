"""Background worker that polls the documents table for PENDING docs and
processes them with semaphore-limited concurrency.

Replaces the fire-and-forget asyncio.create_task() pattern to prevent
overwhelming the embedding API with too many concurrent requests.
"""

import asyncio
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.document import Document, DocumentStatus
from app.services.document_service import DocumentService

logger = logging.getLogger(__name__)


class PipelineWorker:
    """DB-backed pipeline worker with controlled concurrency.

    The worker polls the documents table for PENDING docs, picks them up,
    and runs the pipeline with at most `max_concurrency` simultaneous tasks.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        max_concurrency: int = 2,
        poll_interval: float = 2.0,
    ):
        self._session_factory = session_factory
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._poll_interval = poll_interval
        self._max_concurrency = max_concurrency
        self._running = False
        self._poll_task: asyncio.Task | None = None
        self._active_tasks: set[asyncio.Task] = set()
        self._active_doc_keys: set[tuple[str, str]] = set()  # (kb_id, doc_id)

    def start(self) -> None:
        """Start the polling loop."""
        if self._running:
            return
        self._running = True
        self._poll_task = asyncio.create_task(self._poll_loop())
        logger.info(
            "PipelineWorker started (max_concurrency=%d, poll_interval=%.1fs)",
            self._max_concurrency, self._poll_interval,
        )

    async def stop(self, timeout: float = 30) -> None:
        """Gracefully stop: wait for active pipelines up to timeout, then cancel."""
        self._running = False

        if self._poll_task is not None:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
            self._poll_task = None

        if self._active_tasks:
            logger.info("Waiting for %d active pipeline(s) to finish...", len(self._active_tasks))
            done, pending = await asyncio.wait(
                self._active_tasks, timeout=timeout
            )
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.wait(pending, timeout=5)
                logger.warning("Cancelled %d pipeline(s) on shutdown", len(pending))

        self._active_tasks.clear()
        self._active_doc_keys.clear()
        logger.info("PipelineWorker stopped")

    async def _poll_loop(self) -> None:
        """Main loop: poll for PENDING docs every poll_interval seconds."""
        while self._running:
            try:
                await self._poll_and_dispatch()
            except Exception:
                logger.exception("Error in pipeline worker poll cycle")
            try:
                await asyncio.sleep(self._poll_interval)
            except asyncio.CancelledError:
                break

    async def _poll_and_dispatch(self) -> None:
        """Fetch PENDING docs and dispatch pipeline tasks."""
        # Calculate available slots
        available = self._max_concurrency - len(self._active_doc_keys)
        if available <= 0:
            return

        async with self._session_factory() as session:
            result = await session.execute(
                select(Document)
                .where(Document.status == DocumentStatus.PENDING)
                .limit(available)
            )
            pending_docs = list(result.scalars().all())

        for doc in pending_docs:
            doc_key = (doc.knowledge_base_id, doc.doc_id)
            if doc_key in self._active_doc_keys:
                continue

            self._active_doc_keys.add(doc_key)
            task = asyncio.create_task(
                self._run_pipeline_wrapper(
                    doc.knowledge_base_id,
                    doc.doc_id,
                    doc.file_name,
                    doc.needs_vector_cleanup,
                    doc.chunk_size,
                    doc.chunk_overlap,
                )
            )
            self._active_tasks.add(task)
            task.add_done_callback(self._active_tasks.discard)
            task.add_done_callback(lambda t, k=doc_key: self._active_doc_keys.discard(k))

    async def _run_pipeline_wrapper(
        self,
        knowledge_base_id: str,
        doc_id: str,
        file_name: str,
        needs_vector_cleanup: bool,
        chunk_size: int | None,
        chunk_overlap: int | None,
    ) -> None:
        """Acquire semaphore, run pipeline, release."""
        async with self._semaphore:
            async with self._session_factory() as session:
                # Re-fetch doc to get fresh state
                doc_svc = DocumentService(session)
                doc = await doc_svc.get_by_doc_id_and_kb(doc_id, knowledge_base_id)
                if doc is None:
                    logger.warning("Doc %s/%s disappeared, skipping", knowledge_base_id, doc_id)
                    return
                if doc.status != DocumentStatus.PENDING:
                    logger.info("Doc %s/%s no longer PENDING (now %s), skipping", knowledge_base_id, doc_id, doc.status.value)
                    return

                try:
                    await self._run_single_pipeline(session, doc, None)
                except Exception:
                    logger.exception("Pipeline wrapper failed for %s/%s", knowledge_base_id, doc_id)
                    try:
                        await doc_svc.update_status(
                            doc_id, knowledge_base_id, DocumentStatus.FAILED,
                            error_message="Pipeline worker internal error",
                            progress_message=None,
                        )
                    except Exception:
                        pass

    async def _run_single_pipeline(
        self,
        session: AsyncSession,
        doc: Document,
        services_factory,
    ) -> None:
        """Execute the pipeline for a single document.

        This method is the main integration point. It imports and assembles
        the PipelineService with all required dependencies.
        """
        from app.config import get_settings
        from app.dependencies import (
            get_embedding_service,
            get_parsing_service,
            get_sparse_embedding_service,
            get_vector_store_service,
        )
        from app.services.chunking_service import ChunkingService
        from app.services.document_service import DocumentService
        from app.services.pipeline_service import PipelineService

        settings = get_settings()
        doc_svc = DocumentService(session)

        # Handle vector cleanup for re-vectorization
        if doc.needs_vector_cleanup:
            try:
                vs = await get_vector_store_service()
                await vs.delete_by_doc_id(doc.knowledge_base_id, doc.doc_id)
                logger.info("Cleaned up old vectors for %s/%s", doc.knowledge_base_id, doc.doc_id)
            except Exception:
                logger.warning("Vector cleanup failed for %s/%s, continuing", doc.knowledge_base_id, doc.doc_id)
            # Clear the cleanup flag
            doc.needs_vector_cleanup = False
            await session.commit()

        file_path = settings.upload_path / doc.knowledge_base_id / doc.file_name
        if not file_path.exists():
            await doc_svc.update_status(
                doc.doc_id, doc.knowledge_base_id, DocumentStatus.FAILED,
                error_message=f"Original file not found: {file_path}",
                progress_message=None,
            )
            return

        pipeline = PipelineService(
            session=session,
            parsing_service=get_parsing_service(),
            chunking_service=ChunkingService(
                chunk_size=doc.chunk_size, chunk_overlap=doc.chunk_overlap,
            ),
            embedding_service=get_embedding_service(),
            sparse_embedding_service=get_sparse_embedding_service(),
            vector_store_service=await get_vector_store_service(),
            task_manager=None,
        )

        await pipeline.run_pipeline(
            task_id="worker",
            file_path=str(file_path),
            doc_id=doc.doc_id,
            file_name=doc.file_name,
            knowledge_base_id=doc.knowledge_base_id,
        )
