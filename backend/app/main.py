import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

# Disable LlamaIndex telemetry — prevents network calls in air-gapped environments
os.environ.setdefault("LLAMA_INDEX_DISABLE_TELEMETRY", "true")

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.config import get_settings
from app.core.httpx_client import close_httpx_client
from app.core.qdrant import close_qdrant_client
from app.db.session import close_db, init_db
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

    yield

    # Cleanup
    await close_httpx_client()
    await close_qdrant_client()
    await close_db()
    logger.info("Shutdown complete")


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

    # Exception handlers
    register_exception_handlers(app)

    # Routes
    app.include_router(api_router)

    return app


app = create_app()
