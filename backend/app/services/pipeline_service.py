import logging

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
        task_manager: TaskManager,
    ):
        self.session = session
        self.parsing = parsing_service
        self.chunking = chunking_service
        self.embedding = embedding_service
        self.sparse_embedding = sparse_embedding_service
        self.vector_store = vector_store_service
        self.task_manager = task_manager
        self.doc_service = DocumentService(session)

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
            # Step 1: Parse
            self.task_manager.update_task(
                task_id, status=TaskStatus.PROCESSING, progress="Parsing document..."
            )
            await self.doc_service.update_status(
                doc_id, knowledge_base_id, DocumentStatus.PARSING
            )
            markdown_text = await self.parsing.parse_file(file_path)

            if not markdown_text.strip():
                await self.doc_service.update_status(
                    doc_id, knowledge_base_id, DocumentStatus.COMPLETED, chunk_count=0
                )
                self.task_manager.update_task(
                    task_id,
                    status=TaskStatus.COMPLETED,
                    progress="Completed (empty document)",
                    result={"doc_id": doc_id, "chunk_count": 0},
                )
                return

            # Step 2: Chunk
            self.task_manager.update_task(task_id, progress="Chunking document...")
            await self.doc_service.update_status(
                doc_id, knowledge_base_id, DocumentStatus.CHUNKING
            )
            nodes = self.chunking.chunk_markdown(
                markdown_text, doc_id, file_name, knowledge_base_id
            )

            if not nodes:
                await self.doc_service.update_status(
                    doc_id, knowledge_base_id, DocumentStatus.COMPLETED, chunk_count=0
                )
                self.task_manager.update_task(
                    task_id,
                    status=TaskStatus.COMPLETED,
                    progress="Completed (no chunks)",
                    result={"doc_id": doc_id, "chunk_count": 0},
                )
                return

            # Step 3: Embed (dense)
            self.task_manager.update_task(
                task_id, progress=f"Embedding {len(nodes)} chunks (dense)..."
            )
            await self.doc_service.update_status(
                doc_id, knowledge_base_id, DocumentStatus.EMBEDDING
            )
            texts = [node.text for node in nodes]
            dense_vectors = await self.embedding.embed_texts(texts)

            # Step 4: Embed (sparse)
            self.task_manager.update_task(
                task_id, progress=f"Embedding {len(nodes)} chunks (sparse)..."
            )
            sparse_vectors = await self.sparse_embedding.embed_texts_async(texts)

            # Step 5: Upsert to vector store (delete-before-insert)
            self.task_manager.update_task(task_id, progress="Upserting to vector store...")
            await self.doc_service.update_status(
                doc_id, knowledge_base_id, DocumentStatus.UPSERTING
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
                }
                payloads.append(payload)

            await self.vector_store.upsert_points(
                knowledge_base_id, dense_vectors, sparse_vectors, payloads
            )

            # Step 6: Done
            await self.doc_service.update_status(
                doc_id, knowledge_base_id, DocumentStatus.COMPLETED,
                chunk_count=len(nodes),
            )
            self.task_manager.update_task(
                task_id,
                status=TaskStatus.COMPLETED,
                progress="Completed",
                result={"doc_id": doc_id, "chunk_count": len(nodes)},
            )
            logger.info(
                f"Pipeline completed: doc_id={doc_id}, chunks={len(nodes)}"
            )

        except Exception as e:
            logger.error(f"Pipeline failed for doc_id={doc_id}: {e}", exc_info=True)
            try:
                await self.doc_service.update_status(
                    doc_id, knowledge_base_id, DocumentStatus.FAILED,
                    error_message=str(e)[:1000],
                )
            except Exception:
                pass
            self.task_manager.update_task(
                task_id,
                status=TaskStatus.FAILED,
                error=str(e),
            )
