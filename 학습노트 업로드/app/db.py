"""퀴즈 모듈 비동기 DB 세션.

기본값은 로컬 sqlite입니다. Postgres를 쓰려면 QUIZ_DATABASE_URL에
`postgresql+asyncpg://...` 를 넣습니다.
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

DEFAULT_DATABASE_URL = "sqlite+aiosqlite:///./data/quiz.db"


class Base(DeclarativeBase):
    pass


_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None
_schema_ready = False
_schema_lock = asyncio.Lock()


def database_url() -> str:
    return os.getenv("QUIZ_DATABASE_URL", "").strip() or DEFAULT_DATABASE_URL


def _prepare_sqlite_path(url: str) -> None:
    prefix = "sqlite+aiosqlite:///"
    if not url.startswith(prefix):
        return
    raw = url[len(prefix) :]
    if raw.startswith("file:") or raw == ":memory:":
        return
    path = Path(raw)
    if not path.is_absolute():
        path = Path.cwd() / path
    path.parent.mkdir(parents=True, exist_ok=True)


def _enable_sqlite_foreign_keys(engine: AsyncEngine) -> None:
    if not str(engine.url).startswith("sqlite"):
        return

    @event.listens_for(engine.sync_engine, "connect")
    def _set_pragma(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        url = database_url()
        _prepare_sqlite_path(url)
        kwargs: dict = {
            "json_serializer": lambda value: json.dumps(value, ensure_ascii=False),
            "json_deserializer": json.loads,
        }
        if url.startswith("sqlite"):
            kwargs["connect_args"] = {"check_same_thread": False}
            kwargs["poolclass"] = NullPool
        else:
            kwargs["pool_pre_ping"] = True
        _engine = create_async_engine(url, **kwargs)
        _enable_sqlite_foreign_keys(_engine)
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            get_engine(),
            expire_on_commit=False,
            class_=AsyncSession,
        )
    return _session_factory


def reset_quiz_database() -> None:
    """테스트에서 URL을 바꾼 뒤 엔진을 다시 만들 때 사용합니다."""
    global _engine, _session_factory, _schema_ready
    if _engine is not None:
        _engine.sync_engine.dispose()
    _engine = None
    _session_factory = None
    _schema_ready = False


async def dispose_quiz_database() -> None:
    global _engine, _session_factory, _schema_ready
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None
    _schema_ready = False


async def ensure_quiz_schema() -> None:
    global _schema_ready
    if _schema_ready:
        return
    async with _schema_lock:
        if _schema_ready:
            return
        await init_quiz_models()
        _schema_ready = True


async def init_quiz_models() -> None:
    import app.models.quiz  # noqa: F401

    async with get_engine().begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    await ensure_quiz_schema()
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_session() -> AsyncIterator[AsyncSession]:
    async with session_scope() as session:
        yield session
