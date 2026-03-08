import hashlib
import logging

from app.config import get_settings
from app.services.bm25_service import BM25Service
from app.services.embedding_service import EmbeddingService
from app.services.query_rewrite_service import QueryRewriteService, RewritePlan
from app.services.reranker_service import RerankerService
from app.services.sparse_embedding_service import SparseEmbeddingService
from app.services.vector_store_service import VectorStoreService

logger = logging.getLogger(__name__)


async def synthesize_context(
    source_nodes: list[dict],
    knowledge_base_id: str,
    vector_store: VectorStoreService,
    enable_context_synthesis: bool = True,
) -> list[dict]:
    """Enrich source_nodes with adjacent chunk context (context_text)."""
    if not source_nodes:
        return source_nodes

    if not enable_context_synthesis:
        for node in source_nodes:
            node["context_text"] = node["text"]
        return source_nodes

    doc_ids = {n["doc_id"] for n in source_nodes if n.get("doc_id")}
    doc_chunk_map: dict[str, dict[int, str]] = {}
    for doc_id in doc_ids:
        try:
            chunks = await vector_store.get_chunks_by_doc_id(knowledge_base_id, doc_id)
            doc_chunk_map[doc_id] = {c["chunk_index"]: c["text"] for c in chunks}
        except Exception:
            doc_chunk_map[doc_id] = {}

    for node in source_nodes:
        doc_id = node.get("doc_id", "")
        chunk_index = node.get("chunk_index")
        chunk_map = doc_chunk_map.get(doc_id, {})
        if chunk_index is None or not chunk_map:
            node["context_text"] = node["text"]
            continue

        parts = []
        for candidate_index in (chunk_index - 1, chunk_index, chunk_index + 1):
            if candidate_index in chunk_map:
                parts.append(chunk_map[candidate_index])
        node["context_text"] = "\n\n".join(parts) if parts else node["text"]

    return source_nodes


class RetrievalService:
    """Orchestrates query rewrite, retrieval, reranking, and context synthesis."""

    def __init__(
        self,
        embedding_service: EmbeddingService,
        sparse_embedding_service: SparseEmbeddingService,
        vector_store_service: VectorStoreService,
        reranker_service: RerankerService,
        bm25_service: BM25Service | None = None,
        query_rewrite_service: QueryRewriteService | None = None,
    ):
        self.embedding = embedding_service
        self.sparse_embedding = sparse_embedding_service
        self.vector_store = vector_store_service
        self.reranker = reranker_service
        self.bm25 = bm25_service
        self.query_rewriter = query_rewrite_service

    async def retrieve(
        self,
        knowledge_base_id: str,
        query: str,
        top_k: int = 20,
        top_n: int = 3,
        min_score: float | None = None,
        enable_reranker: bool = True,
        enable_context_synthesis: bool = True,
        enable_query_rewrite: bool = False,
        query_rewrite_debug: bool = False,
    ) -> dict:
        """Execute retrieval pipeline with optional query rewrite fanout."""
        effective_min_score = self._resolve_min_score(min_score, enable_reranker)
        query_plan = await self._build_query_plan(query, enable_query_rewrite)
        candidates, candidate_stats = await self._collect_candidates(
            knowledge_base_id=knowledge_base_id,
            queries=query_plan.final_queries,
            top_k=top_k,
        )

        if not candidates:
            return self._build_result(
                source_nodes=[],
                total_candidates=0,
                top_k=top_k,
                top_n=top_n,
                effective_min_score=effective_min_score,
                enable_reranker=enable_reranker,
                enable_context_synthesis=enable_context_synthesis,
                query_rewrite_debug=query_rewrite_debug,
                query_plan=query_plan,
                candidate_stats=candidate_stats,
            )

        source_nodes = await self._rank_candidates(
            raw_query=query,
            candidates=candidates,
            top_n=top_n,
            enable_reranker=enable_reranker,
        )

        if effective_min_score > 0:
            source_nodes = [node for node in source_nodes if node["score"] >= effective_min_score]

        source_nodes = await synthesize_context(
            source_nodes,
            knowledge_base_id,
            self.vector_store,
            enable_context_synthesis=enable_context_synthesis,
        )

        return self._build_result(
            source_nodes=source_nodes,
            total_candidates=len(candidates),
            top_k=top_k,
            top_n=top_n,
            effective_min_score=effective_min_score,
            enable_reranker=enable_reranker,
            enable_context_synthesis=enable_context_synthesis,
            query_rewrite_debug=query_rewrite_debug,
            query_plan=query_plan,
            candidate_stats=candidate_stats,
        )

    def _resolve_min_score(self, min_score: float | None, enable_reranker: bool) -> float:
        if min_score is not None:
            return min_score
        if enable_reranker:
            return get_settings().reranker_min_score
        return 0.0

    async def _build_query_plan(
        self,
        query: str,
        enable_query_rewrite: bool,
    ) -> RewritePlan:
        if not enable_query_rewrite:
            return RewritePlan.passthrough(query, enabled=False, reason="disabled_by_flag")
        if self.query_rewriter is None:
            return RewritePlan.passthrough(
                query,
                enabled=True,
                reason="rewrite_service_unavailable",
                fallback_used=True,
            )

        try:
            return await self.query_rewriter.build_plan(query)
        except Exception as exc:
            settings = get_settings()
            logger.warning("Query rewrite failed, falling back to raw query: %s", exc)
            return RewritePlan.passthrough(
                query,
                enabled=True,
                reason="rewrite_error",
                fallback_used=True,
                model=settings.query_rewrite_model,
            )

    async def _collect_candidates(
        self,
        knowledge_base_id: str,
        queries: list[str],
        top_k: int,
    ) -> tuple[list[dict], dict]:
        merged_candidates: dict[str, dict] = {}
        raw_candidate_count = 0

        for current_query in queries:
            query_candidates = await self._search_single_query(
                knowledge_base_id=knowledge_base_id,
                query=current_query,
                top_k=top_k,
            )
            raw_candidate_count += len(query_candidates)
            self._merge_query_candidates(merged_candidates, current_query, query_candidates)

        merged_list = sorted(
            merged_candidates.values(),
            key=lambda item: item["score"],
            reverse=True,
        )
        rerank_pool_limit = self._resolve_rerank_pool_limit(top_k, len(queries))
        rerank_candidates = merged_list[:rerank_pool_limit]
        candidate_stats = {
            "query_count": len(queries),
            "raw_candidate_count": raw_candidate_count,
            "merged_candidate_count": len(merged_list),
            "rerank_pool_size": len(rerank_candidates),
        }
        return rerank_candidates, candidate_stats

    async def _search_single_query(
        self,
        knowledge_base_id: str,
        query: str,
        top_k: int,
    ) -> list[dict]:
        dense_vector = await self.embedding.embed_query(query)
        sparse_vector = await self.sparse_embedding.embed_query_async(query)
        bm25_vector = self.bm25.text_to_sparse_vector(query) if self.bm25 is not None else None
        return await self.vector_store.hybrid_search(
            collection_name=knowledge_base_id,
            dense_vector=dense_vector,
            sparse_vector=sparse_vector,
            top_k=top_k,
            bm25_vector=bm25_vector,
        )

    def _merge_query_candidates(
        self,
        merged_candidates: dict[str, dict],
        query: str,
        query_candidates: list[dict],
    ) -> None:
        for candidate in query_candidates:
            payload = candidate.get("payload", {})
            key = self._candidate_key(payload)
            score = float(candidate.get("score", 0.0))
            existing = merged_candidates.get(key)

            if existing is None:
                merged_candidates[key] = {
                    "id": candidate.get("id"),
                    "payload": payload,
                    "matched_queries": [query],
                    "query_scores": {query: score},
                    "max_score": score,
                    "score": score,
                }
                continue

            if query not in existing["matched_queries"]:
                existing["matched_queries"].append(query)
            existing["query_scores"][query] = score
            if score > existing["max_score"]:
                existing["id"] = candidate.get("id")
                existing["payload"] = payload
                existing["max_score"] = score

            coverage_bonus = 0.001 * max(len(existing["matched_queries"]) - 1, 0)
            existing["score"] = existing["max_score"] + coverage_bonus

    def _candidate_key(self, payload: dict) -> str:
        doc_id = payload.get("doc_id")
        chunk_index = payload.get("chunk_index")
        if doc_id and chunk_index is not None:
            return f"{doc_id}:{chunk_index}"
        text = payload.get("text", "")
        return hashlib.sha1(text.encode("utf-8")).hexdigest()

    def _resolve_rerank_pool_limit(self, top_k: int, query_count: int) -> int:
        if query_count <= 1:
            return top_k
        settings = get_settings()
        return min(
            settings.query_rewrite_rerank_pool_size,
            max(top_k, top_k * query_count),
        )

    async def _rank_candidates(
        self,
        raw_query: str,
        candidates: list[dict],
        top_n: int,
        enable_reranker: bool,
    ) -> list[dict]:
        if not candidates:
            return []

        if enable_reranker:
            texts = [candidate["payload"].get("text", "") for candidate in candidates]
            reranked = await self.reranker.rerank(raw_query, texts, top_n=top_n)
            source_nodes = []
            for item in reranked:
                index = item["index"]
                if index < len(candidates):
                    source_nodes.append(
                        self._candidate_to_source_node(candidates[index], item["score"])
                    )
            return source_nodes

        return [
            self._candidate_to_source_node(candidate, candidate["score"])
            for candidate in candidates[:top_n]
        ]

    def _candidate_to_source_node(self, candidate: dict, score: float) -> dict:
        payload = candidate["payload"]
        metadata = {
            key: value
            for key, value in payload.items()
            if key not in {"text", "doc_id", "file_name", "knowledge_base_id"}
        }
        metadata.update({
            "matched_queries": candidate.get("matched_queries", []),
            "query_scores": candidate.get("query_scores", {}),
            "merge_score": candidate.get("score", score),
        })
        return {
            "text": payload.get("text", ""),
            "score": score,
            "doc_id": payload.get("doc_id", ""),
            "file_name": payload.get("file_name", ""),
            "knowledge_base_id": payload.get("knowledge_base_id", ""),
            "chunk_index": payload.get("chunk_index"),
            "header_path": payload.get("header_path"),
            "metadata": metadata,
        }

    def _build_result(
        self,
        source_nodes: list[dict],
        total_candidates: int,
        top_k: int,
        top_n: int,
        effective_min_score: float,
        enable_reranker: bool,
        enable_context_synthesis: bool,
        query_rewrite_debug: bool,
        query_plan: RewritePlan,
        candidate_stats: dict,
    ) -> dict:
        result = {
            "source_nodes": source_nodes,
            "total_candidates": total_candidates,
            "top_k_used": top_k,
            "top_n_used": top_n,
            "min_score_used": effective_min_score,
            "enable_reranker_used": enable_reranker,
            "enable_context_synthesis_used": enable_context_synthesis,
        }
        if query_rewrite_debug:
            result["debug"] = {
                "query_plan": query_plan.to_debug_dict(),
                "candidate_stats": candidate_stats,
            }
        return result
