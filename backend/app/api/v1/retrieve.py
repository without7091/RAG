import json
import logging

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse

from app.dependencies import get_retrieval_service
from app.exceptions import EmbeddingError, RerankerError, VectorStoreError
from app.schemas.retrieve import RetrieveDebug, RetrieveRequest, RetrieveResponse, SourceNode
from app.services.retrieval_service import RetrievalService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/retrieve", tags=["Retrieve"])


@router.post("", response_model=RetrieveResponse)
async def retrieve(
    request: RetrieveRequest,
    retrieval_service: RetrievalService = Depends(get_retrieval_service),
):
    """Execute retrieval pipeline with optional query rewrite fanout."""
    if request.stream:
        return EventSourceResponse(
            _stream_retrieval(request, retrieval_service),
            media_type="text/event-stream",
        )

    try:
        result = await retrieval_service.retrieve(
            knowledge_base_id=request.knowledge_base_id,
            query=request.query,
            top_k=request.top_k,
            top_n=request.top_n,
            min_score=request.min_score,
            enable_reranker=request.enable_reranker,
            enable_context_synthesis=request.enable_context_synthesis,
            enable_query_rewrite=request.enable_query_rewrite,
            query_rewrite_debug=request.query_rewrite_debug,
        )
    except (EmbeddingError, RerankerError) as exc:
        return JSONResponse(status_code=502, content={"detail": str(exc)})
    except VectorStoreError as exc:
        return JSONResponse(status_code=500, content={"detail": str(exc)})
    except Exception as exc:
        logger.error("Retrieval failed: %s", exc, exc_info=True)
        return JSONResponse(status_code=500, content={"detail": f"Retrieval failed: {exc}"})

    return _build_response_model(request, result)


def _build_response_model(request: RetrieveRequest, result: dict) -> RetrieveResponse:
    source_nodes = [SourceNode(**node) for node in result["source_nodes"]]
    debug = RetrieveDebug(**result["debug"]) if result.get("debug") else None
    return RetrieveResponse(
        query=request.query,
        knowledge_base_id=request.knowledge_base_id,
        source_nodes=source_nodes,
        total_candidates=result["total_candidates"],
        top_k_used=result["top_k_used"],
        top_n_used=result["top_n_used"],
        min_score_used=result.get("min_score_used"),
        enable_reranker_used=result.get("enable_reranker_used", True),
        enable_context_synthesis_used=result.get("enable_context_synthesis_used", True),
        debug=debug,
    )


async def _stream_retrieval(
    request: RetrieveRequest,
    retrieval_service: RetrievalService,
):
    """SSE generator for retrieval progress and final result."""
    rewrite_enabled = request.enable_query_rewrite

    try:
        if rewrite_enabled:
            yield {"event": "status", "data": json.dumps({"step": "query_rewrite"})}
        yield {"event": "status", "data": json.dumps({"step": "embedding_query"})}
        yield {"event": "status", "data": json.dumps({"step": "hybrid_search"})}

        result = await retrieval_service.retrieve(
            knowledge_base_id=request.knowledge_base_id,
            query=request.query,
            top_k=request.top_k,
            top_n=request.top_n,
            min_score=request.min_score,
            enable_reranker=request.enable_reranker,
            enable_context_synthesis=request.enable_context_synthesis,
            enable_query_rewrite=request.enable_query_rewrite,
            query_rewrite_debug=request.query_rewrite_debug,
        )

        rerank_step = "reranking" if request.enable_reranker else "skipping_reranker"
        yield {
            "event": "status",
            "data": json.dumps({
                "step": rerank_step,
                "candidates": result["total_candidates"],
            }),
        }
        context_step = (
            "context_synthesis"
            if request.enable_context_synthesis
            else "skipping_context_synthesis"
        )
        yield {"event": "status", "data": json.dumps({"step": context_step})}
        yield {"event": "status", "data": json.dumps({"step": "building_response"})}
        yield {
            "event": "result",
            "data": _build_response_model(request, result).model_dump_json(),
        }
    except Exception as exc:
        logger.error("Streaming retrieval failed: %s", exc, exc_info=True)
        yield {"event": "error", "data": json.dumps({"error": str(exc)})}
