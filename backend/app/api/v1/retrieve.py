import asyncio
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
    """SSE generator for retrieval progress and final result.

    Uses an asyncio.Queue so that status events from the retrieval service are
    emitted in real time as each step actually executes, rather than all being
    sent upfront before any work begins.
    """
    status_queue: asyncio.Queue[dict] = asyncio.Queue()

    async def status_callback(step: str, **extra: object) -> None:
        await status_queue.put({"step": step, **extra})

    retrieve_task: asyncio.Task = asyncio.ensure_future(
        retrieval_service.retrieve(
            knowledge_base_id=request.knowledge_base_id,
            query=request.query,
            top_k=request.top_k,
            top_n=request.top_n,
            min_score=request.min_score,
            enable_reranker=request.enable_reranker,
            enable_context_synthesis=request.enable_context_synthesis,
            enable_query_rewrite=request.enable_query_rewrite,
            query_rewrite_debug=request.query_rewrite_debug,
            status_callback=status_callback,
        )
    )

    try:
        # Drain status events while the retrieval task is running
        while not retrieve_task.done():
            try:
                data = await asyncio.wait_for(status_queue.get(), timeout=0.05)
                yield {"event": "status", "data": json.dumps(data)}
            except asyncio.TimeoutError:
                pass

        # Drain any status events that were queued after the task finished
        while not status_queue.empty():
            data = status_queue.get_nowait()
            yield {"event": "status", "data": json.dumps(data)}

        # Re-raise if the task failed
        exc = retrieve_task.exception()
        if exc is not None:
            raise exc

        result = retrieve_task.result()
        yield {
            "event": "result",
            "data": _build_response_model(request, result).model_dump_json(),
        }
    except Exception as exc:
        retrieve_task.cancel()
        logger.error("Streaming retrieval failed: %s", exc, exc_info=True)
        yield {"event": "error", "data": json.dumps({"error": str(exc)})}
