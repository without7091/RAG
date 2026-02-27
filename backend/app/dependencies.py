from collections.abc import AsyncGenerator

from app.db.session import get_session
from app.services.chunking_service import ChunkingService
from app.services.document_service import DocumentService
from app.services.embedding_service import EmbeddingService
from app.services.kb_service import KBService
from app.services.parsing_service import ParsingService
from app.services.reranker_service import RerankerService
from app.services.retrieval_service import RetrievalService
from app.services.sparse_embedding_service import SparseEmbeddingService
from app.services.task_manager import TaskManager
from app.services.vector_store_service import VectorStoreService

# Singletons
_task_manager = TaskManager()
_parsing_service = ParsingService()
_chunking_service: ChunkingService | None = None
_embedding_service: EmbeddingService | None = None
_sparse_embedding_service: SparseEmbeddingService | None = None
_reranker_service: RerankerService | None = None
_vector_store_service: VectorStoreService | None = None


def get_task_manager() -> TaskManager:
    return _task_manager


def get_parsing_service() -> ParsingService:
    return _parsing_service


def get_chunking_service() -> ChunkingService:
    global _chunking_service
    if _chunking_service is None:
        _chunking_service = ChunkingService()
    return _chunking_service


def get_embedding_service() -> EmbeddingService:
    global _embedding_service
    if _embedding_service is None:
        _embedding_service = EmbeddingService()
    return _embedding_service


def get_sparse_embedding_service() -> SparseEmbeddingService:
    global _sparse_embedding_service
    if _sparse_embedding_service is None:
        _sparse_embedding_service = SparseEmbeddingService()
    return _sparse_embedding_service


def get_reranker_service() -> RerankerService:
    global _reranker_service
    if _reranker_service is None:
        _reranker_service = RerankerService()
    return _reranker_service


async def get_vector_store_service() -> VectorStoreService:
    global _vector_store_service
    if _vector_store_service is None:
        from app.core.qdrant import get_qdrant_client

        client = await get_qdrant_client()
        _vector_store_service = VectorStoreService(client)
    return _vector_store_service


async def get_kb_service_dep() -> AsyncGenerator[KBService, None]:
    async for session in get_session():
        yield KBService(session)


async def get_doc_service_dep() -> AsyncGenerator[DocumentService, None]:
    async for session in get_session():
        yield DocumentService(session)


async def get_retrieval_service() -> RetrievalService:
    vs = await get_vector_store_service()
    return RetrievalService(
        embedding_service=get_embedding_service(),
        sparse_embedding_service=get_sparse_embedding_service(),
        vector_store_service=vs,
        reranker_service=get_reranker_service(),
    )
