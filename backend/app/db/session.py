from collections.abc import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.models import document as _document  # noqa: F401
from app.models import kb_folder as _kb_folder  # noqa: F401
from app.models import knowledge_base as _knowledge_base  # noqa: F401
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
        for col in (
            "chunk_size INTEGER",
            "chunk_overlap INTEGER",
            "progress_message VARCHAR(256)",
            "needs_vector_cleanup BOOLEAN DEFAULT 0",
            "is_pre_chunked BOOLEAN DEFAULT 0",
        ):
            try:
                await conn.execute(text(f"ALTER TABLE documents ADD COLUMN {col}"))
            except Exception:
                pass  # column already exists
        try:
            await conn.execute(text("ALTER TABLE knowledge_bases ADD COLUMN folder_id VARCHAR(64)"))
        except Exception:
            pass  # column already exists

    from app.services.kb_folder_service import KBFolderService
    from app.services.kb_service import KBService

    factory = create_session_factory(engine)
    async with factory() as session:
        folder_service = KBFolderService(session)
        await folder_service.ensure_default_hierarchy()
        await KBService(session, folder_service=folder_service).assign_default_folder_to_unassigned()


async def close_db() -> None:
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None
