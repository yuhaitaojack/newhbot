from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import StaticPool

from app.core.config import Settings


class Base(DeclarativeBase):
    pass


def _ensure_sqlite_dir(database_url: str) -> None:
    if "sqlite" not in database_url:
        return
    # sqlite+aiosqlite:///./data/newhbot.db
    if ":///" not in database_url:
        return
    raw_path = database_url.split(":///", 1)[1]
    if raw_path in {":memory:", ""}:
        return
    path = Path(raw_path)
    if path.parent.as_posix() not in {".", ""}:
        path.parent.mkdir(parents=True, exist_ok=True)


def create_engine(settings: Settings, *, echo: bool = False) -> AsyncEngine:
    _ensure_sqlite_dir(settings.database_url)
    connect_args: dict[str, object] = {}
    engine_kwargs: dict[str, object] = {"echo": echo, "future": True}
    if settings.database_url.endswith(":memory:"):
        connect_args["check_same_thread"] = False
        engine_kwargs["poolclass"] = StaticPool
        engine_kwargs["connect_args"] = connect_args
    return create_async_engine(settings.database_url, **engine_kwargs)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def configure_sqlite_pragma(engine: AsyncEngine) -> None:
    """WAL + FULL sync. SQLite is the audit store, not exchange truth."""
    if "sqlite" not in str(engine.url):
        return
    async with engine.begin() as conn:
        await conn.exec_driver_sql("PRAGMA journal_mode=WAL")
        await conn.exec_driver_sql("PRAGMA synchronous=FULL")
        await conn.exec_driver_sql("PRAGMA foreign_keys=ON")


async def session_scope(
    factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    async with factory() as session:
        yield session
