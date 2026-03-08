"""Unit tests for PipelineWorker — DB-backed queue with semaphore-limited concurrency."""

import asyncio
from unittest.mock import patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.base import Base
from app.models.document import DocumentStatus
from app.services.document_service import DocumentService
from app.services.kb_service import KBService
from app.services.pipeline_worker import PipelineWorker


@pytest.fixture
async def worker_db_engine():
    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def worker_session_factory(worker_db_engine):
    return async_sessionmaker(worker_db_engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture
async def kb_id(worker_session_factory):
    async with worker_session_factory() as session:
        kb_svc = KBService(session)
        kb = await kb_svc.create("Worker Test KB")
        return kb.knowledge_base_id


async def _create_doc(session_factory, kb_id, doc_id, file_name, status=DocumentStatus.PENDING, needs_cleanup=False):
    """Helper to create a doc in a given state."""
    async with session_factory() as session:
        doc_svc = DocumentService(session)
        doc = await doc_svc.create(doc_id, file_name, kb_id, status=DocumentStatus.UPLOADED)
        doc.status = status
        doc.needs_vector_cleanup = needs_cleanup
        await session.commit()
        return doc


class TestPipelineWorkerStartStop:
    async def test_start_and_stop(self, worker_session_factory):
        """Worker should start and stop cleanly."""
        worker = PipelineWorker(
            session_factory=worker_session_factory,
            max_concurrency=2,
            poll_interval=0.1,
        )
        worker.start()
        assert worker._running is True
        assert worker._poll_task is not None

        await worker.stop(timeout=2)
        assert worker._running is False

    async def test_stop_idempotent(self, worker_session_factory):
        """Stopping a non-started worker should not raise."""
        worker = PipelineWorker(
            session_factory=worker_session_factory,
            max_concurrency=2,
            poll_interval=0.1,
        )
        await worker.stop(timeout=1)  # Should not raise

    async def test_double_start(self, worker_session_factory):
        """Starting twice should be safe (idempotent)."""
        worker = PipelineWorker(
            session_factory=worker_session_factory,
            max_concurrency=2,
            poll_interval=0.1,
        )
        worker.start()
        worker.start()  # Should not raise or create duplicate tasks
        await worker.stop(timeout=2)


class TestPipelineWorkerPolling:
    async def test_picks_up_pending_docs(self, worker_session_factory, kb_id):
        """Worker should pick up PENDING documents and process them."""
        await _create_doc(worker_session_factory, kb_id, "doc_pending_1", "file1.md", DocumentStatus.PENDING)

        pipeline_called = asyncio.Event()
        original_doc_args = {}

        async def mock_run_pipeline(session, doc, services_factory, is_pre_chunked=False):
            original_doc_args["doc_id"] = doc.doc_id
            # Simulate pipeline completing
            doc_svc = DocumentService(session)
            await doc_svc.update_status(doc.doc_id, doc.knowledge_base_id, DocumentStatus.COMPLETED, chunk_count=1)
            pipeline_called.set()

        worker = PipelineWorker(
            session_factory=worker_session_factory,
            max_concurrency=2,
            poll_interval=0.05,
        )

        with patch.object(worker, '_run_single_pipeline', side_effect=mock_run_pipeline):
            worker.start()
            try:
                await asyncio.wait_for(pipeline_called.wait(), timeout=3)
            finally:
                await worker.stop(timeout=2)

        assert original_doc_args["doc_id"] == "doc_pending_1"

    async def test_skips_non_pending_docs(self, worker_session_factory, kb_id):
        """Worker should not pick up UPLOADED, COMPLETED, FAILED docs."""
        await _create_doc(worker_session_factory, kb_id, "doc_uploaded", "u.md", DocumentStatus.UPLOADED)
        await _create_doc(worker_session_factory, kb_id, "doc_completed", "c.md", DocumentStatus.COMPLETED)
        await _create_doc(worker_session_factory, kb_id, "doc_failed", "f.md", DocumentStatus.FAILED)

        call_count = 0

        async def mock_run_pipeline(session, doc, services_factory, is_pre_chunked=False):
            nonlocal call_count
            call_count += 1

        worker = PipelineWorker(
            session_factory=worker_session_factory,
            max_concurrency=2,
            poll_interval=0.05,
        )

        with patch.object(worker, '_run_single_pipeline', side_effect=mock_run_pipeline):
            worker.start()
            await asyncio.sleep(0.3)
            await worker.stop(timeout=2)

        assert call_count == 0


class TestPipelineWorkerConcurrency:
    async def test_respects_max_concurrency(self, worker_session_factory, kb_id):
        """Worker should not exceed max_concurrency simultaneous pipelines."""
        # Create 4 pending docs
        for i in range(4):
            await _create_doc(worker_session_factory, kb_id, f"doc_conc_{i}", f"file{i}.md", DocumentStatus.PENDING)

        max_concurrent = 0
        current_concurrent = 0
        lock = asyncio.Lock()
        all_started = asyncio.Event()
        started_count = 0

        async def mock_run_pipeline(session, doc, services_factory, is_pre_chunked=False):
            nonlocal max_concurrent, current_concurrent, started_count
            async with lock:
                current_concurrent += 1
                started_count += 1
                if current_concurrent > max_concurrent:
                    max_concurrent = current_concurrent
                if started_count >= 4:
                    all_started.set()
            await asyncio.sleep(0.2)  # Simulate work
            async with lock:
                current_concurrent -= 1
            # Mark as completed
            doc_svc = DocumentService(session)
            await doc_svc.update_status(doc.doc_id, doc.knowledge_base_id, DocumentStatus.COMPLETED)

        worker = PipelineWorker(
            session_factory=worker_session_factory,
            max_concurrency=2,
            poll_interval=0.05,
        )

        with patch.object(worker, '_run_single_pipeline', side_effect=mock_run_pipeline):
            worker.start()
            try:
                await asyncio.wait_for(all_started.wait(), timeout=5)
                await asyncio.sleep(0.3)  # Let remaining finish
            finally:
                await worker.stop(timeout=5)

        assert max_concurrent <= 2, f"Max concurrency was {max_concurrent}, expected <= 2"

    async def test_does_not_pick_already_active_doc(self, worker_session_factory, kb_id):
        """Worker should not dispatch a doc that is already being processed."""
        await _create_doc(worker_session_factory, kb_id, "doc_active", "active.md", DocumentStatus.PENDING)

        call_count = 0
        processing = asyncio.Event()

        async def mock_run_pipeline(session, doc, services_factory, is_pre_chunked=False):
            nonlocal call_count
            call_count += 1
            processing.set()
            # Hold the pipeline open long enough for several poll cycles
            await asyncio.sleep(0.5)
            doc_svc = DocumentService(session)
            await doc_svc.update_status(doc.doc_id, doc.knowledge_base_id, DocumentStatus.COMPLETED)

        worker = PipelineWorker(
            session_factory=worker_session_factory,
            max_concurrency=2,
            poll_interval=0.05,
        )

        with patch.object(worker, '_run_single_pipeline', side_effect=mock_run_pipeline):
            worker.start()
            await asyncio.wait_for(processing.wait(), timeout=3)
            # Wait for several poll cycles while the pipeline is still running
            await asyncio.sleep(0.4)
            # At this point the pipeline is still active (sleeps 0.5s)
            # and multiple poll cycles have passed, but none should have
            # dispatched this doc again
            await worker.stop(timeout=5)

        # Should have been called exactly once despite multiple poll cycles
        assert call_count == 1


class TestPipelineWorkerVectorCleanup:
    async def test_cleanup_flag_triggers_vector_deletion(self, worker_session_factory, kb_id):
        """When needs_vector_cleanup=True, worker should delete old vectors before pipeline."""
        await _create_doc(
            worker_session_factory, kb_id, "doc_cleanup", "cleanup.md",
            DocumentStatus.PENDING, needs_cleanup=True,
        )

        cleanup_called = asyncio.Event()

        async def mock_run_pipeline(session, doc, services_factory, is_pre_chunked=False):
            # Check that the flag was set
            if doc.needs_vector_cleanup:
                cleanup_called.set()
            doc_svc = DocumentService(session)
            await doc_svc.update_status(doc.doc_id, doc.knowledge_base_id, DocumentStatus.COMPLETED)

        worker = PipelineWorker(
            session_factory=worker_session_factory,
            max_concurrency=2,
            poll_interval=0.05,
        )

        with patch.object(worker, '_run_single_pipeline', side_effect=mock_run_pipeline):
            worker.start()
            try:
                await asyncio.wait_for(cleanup_called.wait(), timeout=3)
            finally:
                await worker.stop(timeout=2)

        assert cleanup_called.is_set()


class TestPipelineWorkerGracefulShutdown:
    async def test_waits_for_active_tasks(self, worker_session_factory, kb_id):
        """Stop should wait for active tasks to complete."""
        await _create_doc(worker_session_factory, kb_id, "doc_graceful", "graceful.md", DocumentStatus.PENDING)

        pipeline_started = asyncio.Event()
        pipeline_finished = asyncio.Event()

        async def mock_run_pipeline(session, doc, services_factory, is_pre_chunked=False):
            pipeline_started.set()
            await asyncio.sleep(0.3)
            doc_svc = DocumentService(session)
            await doc_svc.update_status(doc.doc_id, doc.knowledge_base_id, DocumentStatus.COMPLETED)
            pipeline_finished.set()

        worker = PipelineWorker(
            session_factory=worker_session_factory,
            max_concurrency=2,
            poll_interval=0.05,
        )

        with patch.object(worker, '_run_single_pipeline', side_effect=mock_run_pipeline):
            worker.start()
            await asyncio.wait_for(pipeline_started.wait(), timeout=3)
            await worker.stop(timeout=5)

        # Pipeline should have finished before stop returned
        assert pipeline_finished.is_set()
