from collections.abc import AsyncGenerator

from app.db.session import get_session
from app.services.bm25_service import BM25Service
from app.services.chat_completion_service import ChatCompletionService
from app.services.chunking_service import ChunkingService
from app.services.document_service import DocumentService
from app.services.embedding_service import EmbeddingService
from app.services.kb_folder_service import KBFolderService
from app.services.kb_service import KBService
from app.services.parsing_service import ParsingService
from app.services.pipeline_worker import PipelineWorker
from app.services.query_rewrite_service import QueryRewriteService
from app.services.reranker_service import RerankerService
from app.services.retrieval_service import RetrievalService
from app.services.sparse_embedding_service import SparseEmbeddingService
from app.services.vector_store_service import VectorStoreService

# Singletons
_parsing_service = ParsingService()
_chunking_service: ChunkingService | None = None
_embedding_service: EmbeddingService | None = None
_sparse_embedding_service: SparseEmbeddingService | None = None
_reranker_service: RerankerService | None = None
_chat_completion_service: ChatCompletionService | None = None
_query_rewrite_service: QueryRewriteService | None = None
_vector_store_service: VectorStoreService | None = None
_bm25_service: BM25Service | None = None
_pipeline_worker: PipelineWorker | None = None


def get_pipeline_worker() -> PipelineWorker:
    global _pipeline_worker
    if _pipeline_worker is None:
        from app.config import get_settings
        from app.db.session import get_session_factory

        settings = get_settings()
        _pipeline_worker = PipelineWorker(
            session_factory=get_session_factory(),
            max_concurrency=settings.pipeline_max_concurrency,
            poll_interval=settings.pipeline_poll_interval,
        )
    return _pipeline_worker


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


def get_chat_completion_service() -> ChatCompletionService:
    global _chat_completion_service
    if _chat_completion_service is None:
        _chat_completion_service = ChatCompletionService()
    return _chat_completion_service


def get_query_rewrite_service() -> QueryRewriteService:
    global _query_rewrite_service
    if _query_rewrite_service is None:
        _query_rewrite_service = QueryRewriteService(
            chat_service=get_chat_completion_service()
        )
    return _query_rewrite_service


def get_bm25_service() -> BM25Service:
    global _bm25_service
    if _bm25_service is None:
        from app.config import get_settings

        settings = get_settings()
        stopwords = None
        if settings.bm25_stopwords_path:
            from pathlib import Path

            path = Path(settings.bm25_stopwords_path)
            if path.exists():
                stopwords = set(path.read_text(encoding="utf-8").splitlines())
        _bm25_service = BM25Service(
            vocab_size=settings.bm25_vocab_size,
            stopwords=stopwords,
        )
    return _bm25_service


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


async def get_kb_folder_service_dep() -> AsyncGenerator[KBFolderService, None]:
    async for session in get_session():
        yield KBFolderService(session)


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
        bm25_service=get_bm25_service(),
        query_rewrite_service=get_query_rewrite_service(),
    )
