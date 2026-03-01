import logging
import time

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import DocumentStatus
from app.schemas.common import TaskStatus
from app.services.chunking_service import ChunkingService
from app.services.document_service import DocumentService
from app.services.embedding_service import EmbeddingService
from app.services.parsing_service import ParsingService
from app.services.sparse_embedding_service import SparseEmbeddingService
from app.services.task_manager import TaskManager
from app.services.vector_store_service import VectorStoreService

logger = logging.getLogger(__name__)


class PipelineService:
    """Orchestrates the full document ingestion pipeline:
    parse -> chunk -> embed (dense+sparse) -> upsert to vector store.
    """

    def __init__(
        self,
        session: AsyncSession,
        parsing_service: ParsingService,
        chunking_service: ChunkingService,
        embedding_service: EmbeddingService,
        sparse_embedding_service: SparseEmbeddingService,
        vector_store_service: VectorStoreService,
        task_manager: TaskManager | None = None,
    ):
        self.session = session
        self.parsing = parsing_service
        self.chunking = chunking_service
        self.embedding = embedding_service
        self.sparse_embedding = sparse_embedding_service
        self.vector_store = vector_store_service
        self.task_manager = task_manager
        self.doc_service = DocumentService(session)

    def _update_task(self, task_id: str, **kwargs) -> None:
        """Update task status if task_manager is available, no-op otherwise."""
        if self.task_manager is not None:
            self.task_manager.update_task(task_id, **kwargs)

    async def run_pipeline(
        self,
        task_id: str,
        file_path: str,
        doc_id: str,
        file_name: str,
        knowledge_base_id: str,
    ) -> None:
        """Execute the full ingestion pipeline as a background task."""
        try:
            pipeline_start = time.perf_counter()

            # Step 1: Parse
            self._update_task(
                task_id, status=TaskStatus.PROCESSING, progress="Parsing document..."
            )
            await self.doc_service.update_status(
                doc_id, knowledge_base_id, DocumentStatus.PARSING,
                progress_message="正在解析文档...",
            )
            t0 = time.perf_counter()
            markdown_text = await self.parsing.parse_file(file_path)
            logger.info("Pipeline[%s] parsing: %.1fms", doc_id[:12], (time.perf_counter() - t0) * 1000)

            if not markdown_text.strip():
                await self.doc_service.update_status(
                    doc_id, knowledge_base_id, DocumentStatus.COMPLETED, chunk_count=0
                )
                self._update_task(
                    task_id,
                    status=TaskStatus.COMPLETED,
                    progress="Completed (empty document)",
                    result={"doc_id": doc_id, "chunk_count": 0},
                )
                return

            # Step 2: Chunk
            self._update_task(task_id, progress="Chunking document...")
            await self.doc_service.update_status(
                doc_id, knowledge_base_id, DocumentStatus.CHUNKING,
                progress_message="正在分块...",
            )
            t0 = time.perf_counter()
            nodes = self.chunking.chunk_markdown(
                markdown_text, doc_id, file_name, knowledge_base_id
            )
            logger.info("Pipeline[%s] chunking: %.1fms, %d chunks", doc_id[:12], (time.perf_counter() - t0) * 1000, len(nodes))

            if not nodes:
                await self.doc_service.update_status(
                    doc_id, knowledge_base_id, DocumentStatus.COMPLETED, chunk_count=0
                )
                self._update_task(
                    task_id,
                    status=TaskStatus.COMPLETED,
                    progress="Completed (no chunks)",
                    result={"doc_id": doc_id, "chunk_count": 0},
                )
                return

            # Step 3: Embed (dense)
            self._update_task(
                task_id, progress=f"Embedding {len(nodes)} chunks (dense)..."
            )
            await self.doc_service.update_status(
                doc_id, knowledge_base_id, DocumentStatus.EMBEDDING,
                progress_message=f"正在嵌入 {len(nodes)} 个切片 (dense)...",
            )
            texts = [node.text for node in nodes]
            t0 = time.perf_counter()
            dense_vectors = await self.embedding.embed_texts(texts)
            logger.info("Pipeline[%s] dense embedding: %.1fms, %d vectors", doc_id[:12], (time.perf_counter() - t0) * 1000, len(dense_vectors))

            # Step 4: Embed (sparse)
            self._update_task(
                task_id, progress=f"Embedding {len(nodes)} chunks (sparse)..."
            )
            await self.doc_service.update_status(
                doc_id, knowledge_base_id, DocumentStatus.EMBEDDING,
                progress_message=f"正在嵌入 {len(nodes)} 个切片 (sparse)...",
            )
            t0 = time.perf_counter()
            sparse_vectors = await self.sparse_embedding.embed_texts_async(texts)
            logger.info("Pipeline[%s] sparse embedding: %.1fms, %d vectors", doc_id[:12], (time.perf_counter() - t0) * 1000, len(sparse_vectors))

            # Step 5: Upsert to vector store (delete-before-insert)
            self._update_task(task_id, progress="Upserting to vector store...")
            await self.doc_service.update_status(
                doc_id, knowledge_base_id, DocumentStatus.UPSERTING,
                progress_message="正在写入向量库...",
            )

            # Delete existing vectors for this doc_id first
            await self.vector_store.delete_by_doc_id(knowledge_base_id, doc_id)

            # Build payloads from node metadata
            payloads = []
            for node in nodes:
                payload = {
                    "text": node.text,
                    "doc_id": doc_id,
                    "file_name": file_name,
                    "knowledge_base_id": knowledge_base_id,
                    "chunk_index": node.metadata.get("chunk_index", 0),
                    "header_path": node.metadata.get("header_path", ""),
                    "header_level": node.metadata.get("header_level", 0),
                    "content_type": node.metadata.get("content_type", "text"),
                }
                payloads.append(payload)

            t0 = time.perf_counter()
            await self.vector_store.upsert_points(
                knowledge_base_id, dense_vectors, sparse_vectors, payloads
            )
            logger.info("Pipeline[%s] upsert: %.1fms, %d points", doc_id[:12], (time.perf_counter() - t0) * 1000, len(payloads))

            # Step 6: Done
            total_ms = (time.perf_counter() - pipeline_start) * 1000
            await self.doc_service.update_status(
                doc_id, knowledge_base_id, DocumentStatus.COMPLETED,
                chunk_count=len(nodes),
                progress_message=None,
            )
            self._update_task(
                task_id,
                status=TaskStatus.COMPLETED,
                progress="Completed",
                result={"doc_id": doc_id, "chunk_count": len(nodes)},
            )
            logger.info(
                "Pipeline[%s] completed: %d chunks, total %.1fms",
                doc_id[:12], len(nodes), total_ms,
            )

        except Exception as e:
            logger.error(f"Pipeline failed for doc_id={doc_id}: {e}", exc_info=True)
            try:
                await self.doc_service.update_status(
                    doc_id, knowledge_base_id, DocumentStatus.FAILED,
                    error_message=str(e)[:1000],
                    progress_message=None,
                )
            except Exception:
                pass
            self._update_task(
                task_id,
                status=TaskStatus.FAILED,
                error=str(e),
            )
