import logging

from app.config import get_settings
from app.services.embedding_service import EmbeddingService
from app.services.reranker_service import RerankerService
from app.services.sparse_embedding_service import SparseEmbeddingService
from app.services.vector_store_service import VectorStoreService

logger = logging.getLogger(__name__)


async def synthesize_context(
    source_nodes: list[dict],
    knowledge_base_id: str,
    vector_store: VectorStoreService,
) -> list[dict]:
    """Enrich source_nodes with adjacent chunk context (context_text).

    For each source node, fetches the previous and next chunks from the same
    document and merges them into a single context_text field.
    """
    if not source_nodes:
        return source_nodes

    # Collect unique doc_ids
    doc_ids = {n["doc_id"] for n in source_nodes if n.get("doc_id")}

    # Build {doc_id: {chunk_index: text}} map
    doc_chunk_map: dict[str, dict[int, str]] = {}
    for doc_id in doc_ids:
        try:
            chunks = await vector_store.get_chunks_by_doc_id(
                knowledge_base_id, doc_id
            )
            doc_chunk_map[doc_id] = {c["chunk_index"]: c["text"] for c in chunks}
        except Exception:
            doc_chunk_map[doc_id] = {}

    # Enrich each source node
    for node in source_nodes:
        doc_id = node.get("doc_id", "")
        chunk_index = node.get("chunk_index")
        chunk_map = doc_chunk_map.get(doc_id, {})

        if chunk_index is None or not chunk_map:
            node["context_text"] = node["text"]
            continue

        parts = []
        for ci in (chunk_index - 1, chunk_index, chunk_index + 1):
            if ci in chunk_map:
                parts.append(chunk_map[ci])

        node["context_text"] = "\n\n".join(parts) if parts else node["text"]

    return source_nodes


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
        top_k: int = 20,
        top_n: int = 3,
        min_score: float | None = None,
    ) -> dict:
        """Execute full retrieval pipeline.

        Returns dict with:
        - source_nodes: list of result dicts
        - total_candidates: number of raw candidates
        - top_k_used, top_n_used, min_score_used
        """
        effective_min_score = (
            min_score if min_score is not None
            else get_settings().reranker_min_score
        )

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
                "min_score_used": effective_min_score,
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

        # Step 5: min_score filtering
        if effective_min_score > 0:
            source_nodes = [
                n for n in source_nodes if n["score"] >= effective_min_score
            ]

        # Step 6: Context synthesis — enrich with adjacent chunks
        source_nodes = await synthesize_context(
            source_nodes, knowledge_base_id, self.vector_store
        )

        return {
            "source_nodes": source_nodes,
            "total_candidates": total_candidates,
            "top_k_used": top_k,
            "top_n_used": top_n,
            "min_score_used": effective_min_score,
        }
