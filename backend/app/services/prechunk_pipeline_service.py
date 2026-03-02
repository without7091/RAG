"""Pipeline service for pre-chunked document uploads.

Skips parsing and chunking steps — reads pre-built chunks from JSON,
embeds them (dense + sparse + BM25), and upserts to vector store.
"""

import json
import logging
import time

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import DocumentStatus
from app.services.bm25_service import BM25Service
from app.services.document_service import DocumentService
from app.services.embedding_service import EmbeddingService
from app.services.sparse_embedding_service import SparseEmbeddingService
from app.services.vector_store_service import VectorStoreService

logger = logging.getLogger(__name__)


class PreChunkPipelineService:
    """Pipeline for pre-chunked documents: embed → upsert (skip parse+chunk)."""

    def __init__(
        self,
        session: AsyncSession,
        embedding_service: EmbeddingService,
        sparse_embedding_service: SparseEmbeddingService,
        vector_store_service: VectorStoreService,
        bm25_service: BM25Service | None = None,
    ):
        self.session = session
        self.embedding = embedding_service
        self.sparse_embedding = sparse_embedding_service
        self.vector_store = vector_store_service
        self.bm25 = bm25_service
        self.doc_service = DocumentService(session)

    async def run_pipeline(
        self,
        chunks_json_path: str,
        doc_id: str,
        file_name: str,
        knowledge_base_id: str,
    ) -> None:
        """Execute the pre-chunk pipeline: read JSON → embed → upsert."""
        try:
            pipeline_start = time.perf_counter()

            # Step 1: Read chunks from JSON
            await self.doc_service.update_status(
                doc_id, knowledge_base_id, DocumentStatus.EMBEDDING,
                progress_message="正在读取预切分数据...",
            )

            with open(chunks_json_path, "r", encoding="utf-8") as f:
                chunks_data = json.load(f)

            if not chunks_data:
                await self.doc_service.update_status(
                    doc_id, knowledge_base_id, DocumentStatus.COMPLETED,
                    chunk_count=0,
                    progress_message=None,
                )
                return

            texts = [chunk["text"] for chunk in chunks_data]

            # Step 2: Dense embedding
            await self.doc_service.update_status(
                doc_id, knowledge_base_id, DocumentStatus.EMBEDDING,
                progress_message=f"正在嵌入 {len(texts)} 个切片 (dense)...",
            )
            t0 = time.perf_counter()
            dense_vectors = await self.embedding.embed_texts(texts)
            logger.info(
                "PreChunkPipeline[%s] dense embedding: %.1fms, %d vectors",
                doc_id[:12], (time.perf_counter() - t0) * 1000, len(dense_vectors),
            )

            # Step 3: Sparse embedding
            await self.doc_service.update_status(
                doc_id, knowledge_base_id, DocumentStatus.EMBEDDING,
                progress_message=f"正在嵌入 {len(texts)} 个切片 (sparse)...",
            )
            t0 = time.perf_counter()
            sparse_vectors = await self.sparse_embedding.embed_texts_async(texts)
            logger.info(
                "PreChunkPipeline[%s] sparse embedding: %.1fms, %d vectors",
                doc_id[:12], (time.perf_counter() - t0) * 1000, len(sparse_vectors),
            )

            # Step 4: BM25 vectors
            bm25_vectors = None
            if self.bm25 is not None:
                t0 = time.perf_counter()
                bm25_vectors = self.bm25.batch_to_sparse_vectors(texts)
                logger.info(
                    "PreChunkPipeline[%s] BM25 vectors: %.1fms, %d vectors",
                    doc_id[:12], (time.perf_counter() - t0) * 1000, len(bm25_vectors),
                )

            # Step 5: Upsert to vector store (delete-before-insert)
            await self.doc_service.update_status(
                doc_id, knowledge_base_id, DocumentStatus.UPSERTING,
                progress_message="正在写入向量库...",
            )

            await self.vector_store.delete_by_doc_id(knowledge_base_id, doc_id)

            payloads = []
            for i, chunk in enumerate(chunks_data):
                payload = {
                    "text": chunk["text"],
                    "doc_id": doc_id,
                    "file_name": file_name,
                    "knowledge_base_id": knowledge_base_id,
                    "chunk_index": i,
                    "header_path": chunk.get("header_path", ""),
                    "header_level": chunk.get("header_level", 0),
                    "content_type": chunk.get("content_type", "text"),
                }
                # Merge user-provided metadata
                if chunk.get("metadata"):
                    payload.update(chunk["metadata"])
                payloads.append(payload)

            t0 = time.perf_counter()
            await self.vector_store.upsert_points(
                knowledge_base_id, dense_vectors, sparse_vectors, payloads,
                bm25_vectors=bm25_vectors,
            )
            logger.info(
                "PreChunkPipeline[%s] upsert: %.1fms, %d points",
                doc_id[:12], (time.perf_counter() - t0) * 1000, len(payloads),
            )

            # Step 6: Done
            total_ms = (time.perf_counter() - pipeline_start) * 1000
            await self.doc_service.update_status(
                doc_id, knowledge_base_id, DocumentStatus.COMPLETED,
                chunk_count=len(chunks_data),
                progress_message=None,
            )
            logger.info(
                "PreChunkPipeline[%s] completed: %d chunks, total %.1fms",
                doc_id[:12], len(chunks_data), total_ms,
            )

        except Exception as e:
            logger.error(f"PreChunkPipeline failed for doc_id={doc_id}: {e}", exc_info=True)
            try:
                await self.doc_service.update_status(
                    doc_id, knowledge_base_id, DocumentStatus.FAILED,
                    error_message=str(e)[:1000],
                    progress_message=None,
                )
            except Exception:
                pass
