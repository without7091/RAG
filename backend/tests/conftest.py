import os

# Override settings before any app imports
os.environ["SILICONFLOW_API_KEY"] = "test-key"
os.environ["SQLITE_DATABASE_URL"] = "sqlite+aiosqlite://"
os.environ["QDRANT_STORAGE_PATH"] = ":memory:"
os.environ["UPLOAD_DIR"] = "./test_uploads"
os.environ["SPARSE_EMBEDDING_MODE"] = "api"

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import Settings, get_settings
from app.models.base import Base


@pytest.fixture
def settings() -> Settings:
    return get_settings()


@pytest.fixture
async def db_engine():
    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def db_session(db_engine) -> AsyncSession:
    factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session


@pytest.fixture
async def app_client():
    """Full integration test client with in-memory DB and overrides."""
    from app.db import session as session_mod
    from app.main import create_app

    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    # Override session module globals
    original_engine = session_mod._engine
    original_factory = session_mod._session_factory
    session_mod._engine = engine
    session_mod._session_factory = factory

    app = create_app()

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client

    session_mod._engine = original_engine
    session_mod._session_factory = original_factory
    await engine.dispose()
