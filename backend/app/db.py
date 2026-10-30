"""Async SQLAlchemy engine + session factory."""
import asyncio
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .config import get_config

_engine = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None
_schema_ready = False
_schema_lock = asyncio.Lock()


def init_engine(database_url: str | None = None) -> None:
    global _engine, _sessionmaker, _schema_ready
    url = database_url or get_config().database_url
    _engine = create_async_engine(url, echo=False, future=True)
    _sessionmaker = async_sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)
    _schema_ready = False


def _ensure_init() -> None:
    if _engine is None:
        init_engine()


def get_engine():
    _ensure_init()
    return _engine


async def ensure_schema() -> None:
    """Create tables on first use — covers lazy init without a lifespan."""
    global _schema_ready
    if _schema_ready:
        return
    async with _schema_lock:
        if not _schema_ready:
            await create_all()
            _schema_ready = True


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    _ensure_init()
    await ensure_schema()
    async with _sessionmaker() as session:
        yield session


def session_factory() -> async_sessionmaker[AsyncSession]:
    _ensure_init()
    return _sessionmaker


async def create_all() -> None:
    from .models.domain import Base

    _ensure_init()
    async with _engine.begin() as conn:  # type: ignore[union-attr]
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_additive_columns)
    global _schema_ready
    _schema_ready = True


def _additive_columns(conn) -> None:
    """Idempotent mini-migration for columns added after first release.

    create_all won't ALTER existing tables, so columns added later are
    patched in here — additive only, never destructive.
    """
    from sqlalchemy import inspect, text

    wanted = {
        "quests": {"cheatsheet_md": "TEXT NOT NULL DEFAULT ''"},
        "tracks": {"cheatsheet_md": "TEXT NOT NULL DEFAULT ''"},
    }
    existing_tables = set(inspect(conn).get_table_names())
    for table, cols in wanted.items():
        if table not in existing_tables:
            continue
        have = {c["name"] for c in inspect(conn).get_columns(table)}
        for col, ddl in cols.items():
            if col not in have:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}"))
