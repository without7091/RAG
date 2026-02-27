import logging

from app.services.embedding_service import EmbeddingService
from app.services.reranker_service import RerankerService
from app.services.sparse_embedding_service import SparseEmbeddingService
from app.services.vector_store_service import VectorStoreService

logger = logging.getLogger(__name__)


class RetrievalService:
    """Orchestrates the full retrieval pipeline:
    query embed -> hybrid search -> rerank -> context synthesis.
    """

    def __init__(
        self,
        embedding_service: EmbeddingService,
        sparse_embedding_service: SparseEmbeddingService,
        vector_store_service: VectorStoreService,
        reranker_service: RerankerService,
    ):
        self.embedding = embedding_service
        self.sparse_embedding = sparse_embedding_service
        self.vector_store = vector_store_service
        self.reranker = reranker_service

    async def retrieve(
        self,
        knowledge_base_id: str,
        query: str,
        top_k: int = 10,
        top_n: int = 3,
    ) -> dict:
        """Execute full retrieval pipeline.

        Returns dict with:
        - source_nodes: list of result dicts
        - total_candidates: number of raw candidates
        - top_k_used, top_n_used
        """
        # Step 1: Embed query (dense + sparse)
        dense_vector = await self.embedding.embed_query(query)
        sparse_vector = await self.sparse_embedding.embed_query_async(query)

        # Step 2: Hybrid search
        candidates = await self.vector_store.hybrid_search(
            collection_name=knowledge_base_id,
            dense_vector=dense_vector,
            sparse_vector=sparse_vector,
            top_k=top_k,
        )

        total_candidates = len(candidates)

        if not candidates:
            return {
                "source_nodes": [],
                "total_candidates": 0,
                "top_k_used": top_k,
                "top_n_used": top_n,
            }

        # Step 3: Rerank
        texts = [hit["payload"].get("text", "") for hit in candidates]
        reranked = await self.reranker.rerank(query, texts, top_n=top_n)

        # Step 4: Build source nodes from reranked results
        source_nodes = []
        for item in reranked:
            idx = item["index"]
            if idx < len(candidates):
                candidate = candidates[idx]
                payload = candidate["payload"]
                source_nodes.append({
                    "text": payload.get("text", ""),
                    "score": item["score"],
                    "doc_id": payload.get("doc_id", ""),
                    "file_name": payload.get("file_name", ""),
                    "knowledge_base_id": payload.get("knowledge_base_id", ""),
                    "chunk_index": payload.get("chunk_index"),
                    "header_path": payload.get("header_path"),
                    "metadata": {
                        k: v for k, v in payload.items()
                        if k not in {"text", "doc_id", "file_name", "knowledge_base_id"}
                    },
                })

        return {
            "source_nodes": source_nodes,
            "total_candidates": total_candidates,
            "top_k_used": top_k,
            "top_n_used": top_n,
        }
