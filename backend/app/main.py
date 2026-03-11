import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

# Disable LlamaIndex telemetry — prevents network calls in air-gapped environments
os.environ.setdefault("LLAMA_INDEX_DISABLE_TELEMETRY", "true")

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from starlette.middleware.base import BaseHTTPMiddleware

from app.api.router import api_router
from app.config import get_settings
from app.core.httpx_client import close_httpx_client
from app.core.qdrant import close_qdrant_client
from app.db.session import close_db, get_engine, init_db
from app.dependencies import get_pipeline_worker
from app.exception_handlers import register_exception_handlers

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup/shutdown lifecycle."""
    settings = get_settings()

    # Ensure directories exist
    Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)
    Path(settings.qdrant_storage_path).mkdir(parents=True, exist_ok=True)

    # Initialize database
    await init_db()
    logger.info("Database initialized")

    # Startup recovery: reset docs stuck in processing states
    # SQLAlchemy Enum stores names (uppercase), not values
    engine = get_engine()
    async with engine.begin() as conn:
        result = await conn.execute(
            text(
                "UPDATE documents SET status = 'PENDING', needs_vector_cleanup = 1 "
                "WHERE status IN ('PARSING', 'CHUNKING', 'EMBEDDING', 'UPSERTING')"
            )
        )
        if result.rowcount > 0:
            logger.info("Startup recovery: reset %d stuck document(s) to PENDING", result.rowcount)

    # Start pipeline worker
    worker = get_pipeline_worker()
    worker.start()

    yield

    # Shutdown: stop worker first
    await worker.stop(timeout=30)

    # Cleanup
    await close_httpx_client()
    await close_qdrant_client()
    await close_db()
    logger.info("Shutdown complete")


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = (time.perf_counter() - start) * 1000
        logger.info(
            "%s %s → %d (%.1fms)",
            request.method,
            request.url.path,
            response.status_code,
            elapsed_ms,
        )
        return response


def create_app() -> FastAPI:
    app = FastAPI(
        title="RAG Knowledge Management Platform",
        description="Multi-tenant RAG retrieval middleware API",
        version="0.1.0",
        lifespan=lifespan,
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Request logging
    app.add_middleware(RequestLoggingMiddleware)

    # Exception handlers
    register_exception_handlers(app)

    # Routes
    app.include_router(api_router)

    # MCP Server (mounted as ASGI sub-application at /mcp)
    settings = get_settings()
    if settings.mcp_enabled:
        from app.mcp import create_mcp_server

        mcp_server = create_mcp_server()
        app.mount("/mcp", mcp_server.streamable_http_app())
        logger.info("MCP server mounted at /mcp")

    return app


app = create_app()
