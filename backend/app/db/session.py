from collections.abc import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.models.base import Base


def create_engine(database_url: str | None = None):
    url = database_url or get_settings().sqlite_database_url
    return create_async_engine(url, echo=False)


def create_session_factory(engine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


_engine = None
_session_factory = None


def get_engine():
    global _engine
    if _engine is None:
        _engine = create_engine()
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = create_session_factory(get_engine())
    return _session_factory


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    factory = get_session_factory()
    async with factory() as session:
        yield session


async def init_db(engine=None) -> None:
    engine = engine or get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Migrate: add new columns if missing (SQLite ALTER TABLE)
    async with engine.begin() as conn:
        for col in ("chunk_size INTEGER", "chunk_overlap INTEGER", "progress_message VARCHAR(256)", "needs_vector_cleanup BOOLEAN DEFAULT 0"):
            try:
                await conn.execute(text(f"ALTER TABLE documents ADD COLUMN {col}"))
            except Exception:
                pass  # column already exists


async def close_db() -> None:
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None
