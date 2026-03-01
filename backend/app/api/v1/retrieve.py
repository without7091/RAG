import json
import logging

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse

from app.config import get_settings
from app.dependencies import get_retrieval_service
from app.exceptions import EmbeddingError, RerankerError, VectorStoreError
from app.schemas.retrieve import RetrieveRequest, RetrieveResponse, SourceNode
from app.services.retrieval_service import RetrievalService, synthesize_context

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/retrieve", tags=["Retrieve"])


@router.post("", response_model=RetrieveResponse)
async def retrieve(
    request: RetrieveRequest,
    retrieval_service: RetrievalService = Depends(get_retrieval_service),
):
    """Execute retrieval pipeline: hybrid search -> rerank -> context synthesis.

    Supports SSE streaming mode (stream=true) and JSON mode (stream=false).
    """
    if request.stream:
        return EventSourceResponse(
            _stream_retrieval(request, retrieval_service),
            media_type="text/event-stream",
        )

    # JSON mode
    try:
        result = await retrieval_service.retrieve(
            knowledge_base_id=request.knowledge_base_id,
            query=request.query,
            top_k=request.top_k,
            top_n=request.top_n,
            min_score=request.min_score,
        )
    except (EmbeddingError, RerankerError) as e:
        return JSONResponse(status_code=502, content={"detail": str(e)})
    except VectorStoreError as e:
        return JSONResponse(status_code=500, content={"detail": str(e)})
    except Exception as e:
        logger.error(f"Retrieval failed: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"detail": f"Retrieval failed: {e}"})

    source_nodes = [SourceNode(**node) for node in result["source_nodes"]]
    return RetrieveResponse(
        query=request.query,
        knowledge_base_id=request.knowledge_base_id,
        source_nodes=source_nodes,
        total_candidates=result["total_candidates"],
        top_k_used=result["top_k_used"],
        top_n_used=result["top_n_used"],
        min_score_used=result.get("min_score_used"),
    )


async def _stream_retrieval(
    request: RetrieveRequest,
    retrieval_service: RetrievalService,
):
    """SSE generator for streaming retrieval progress."""
    effective_min_score = (
        request.min_score if request.min_score is not None
        else get_settings().reranker_min_score
    )

    yield {"event": "status", "data": json.dumps({"step": "embedding_query"})}

    try:
        # Embed query
        dense_vector = await retrieval_service.embedding.embed_query(request.query)
        sparse_vector = await retrieval_service.sparse_embedding.embed_query_async(request.query)

        yield {"event": "status", "data": json.dumps({"step": "hybrid_search"})}

        # Hybrid search
        candidates = await retrieval_service.vector_store.hybrid_search(
            collection_name=request.knowledge_base_id,
            dense_vector=dense_vector,
            sparse_vector=sparse_vector,
            top_k=request.top_k,
        )

        yield {
            "event": "status",
            "data": json.dumps({
                "step": "reranking",
                "candidates": len(candidates),
            }),
        }

        if not candidates:
            yield {
                "event": "result",
                "data": json.dumps({
                    "query": request.query,
                    "knowledge_base_id": request.knowledge_base_id,
                    "source_nodes": [],
                    "total_candidates": 0,
                    "top_k_used": request.top_k,
                    "top_n_used": request.top_n,
                    "min_score_used": effective_min_score,
                }),
            }
            return

        # Rerank
        texts = [hit["payload"].get("text", "") for hit in candidates]
        reranked = await retrieval_service.reranker.rerank(
            request.query, texts, top_n=request.top_n
        )

        yield {"event": "status", "data": json.dumps({"step": "building_response"})}

        # Build response
        source_nodes = []
        for item in reranked:
            idx = item["index"]
            if idx < len(candidates):
                payload = candidates[idx]["payload"]
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

        # min_score filtering
        if effective_min_score > 0:
            source_nodes = [
                n for n in source_nodes if n["score"] >= effective_min_score
            ]

        # Context synthesis
        yield {"event": "status", "data": json.dumps({"step": "context_synthesis"})}
        source_nodes = await synthesize_context(
            source_nodes, request.knowledge_base_id, retrieval_service.vector_store
        )

        yield {
            "event": "result",
            "data": json.dumps({
                "query": request.query,
                "knowledge_base_id": request.knowledge_base_id,
                "source_nodes": source_nodes,
                "total_candidates": len(candidates),
                "top_k_used": request.top_k,
                "top_n_used": request.top_n,
                "min_score_used": effective_min_score,
            }),
        }

    except Exception as e:
        logger.error(f"Streaming retrieval failed: {e}", exc_info=True)
        yield {"event": "error", "data": json.dumps({"error": str(e)})}
