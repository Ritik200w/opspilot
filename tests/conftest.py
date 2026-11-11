import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from app.config import Settings, get_settings
from app.db import get_session
from app.main import create_app
from app.models import Base
from app.queue import get_queue

TEST_TOKEN = "test-token-123"


class FakeQueue:
    """Records enqueued incident IDs instead of talking to Redis."""

    def __init__(self) -> None:
        self.enqueued: list[uuid.UUID] = []
        self.fail = False

    async def enqueue_analysis(self, incident_id: uuid.UUID) -> None:
        if self.fail:
            raise ConnectionError("redis down")
        self.enqueued.append(incident_id)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _enable_sqlite_savepoints(engine: AsyncEngine) -> None:
    """pysqlite/aiosqlite manage transactions themselves and break SAVEPOINT (begin_nested).
    Standard SQLAlchemy workaround: disable that and emit BEGIN ourselves."""

    @event.listens_for(engine.sync_engine, "connect")
    def _on_connect(dbapi_connection: Any, _record: Any) -> None:  # noqa: ANN401
        dbapi_connection.isolation_level = None

    @event.listens_for(engine.sync_engine, "begin")
    def _on_begin(conn: Any) -> None:  # noqa: ANN401
        conn.exec_driver_sql("BEGIN")


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    """Fresh in-memory SQLite DB per test, schema built from the models."""
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    _enable_sqlite_savepoints(engine)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
def sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest.fixture
async def session(sessionmaker: async_sessionmaker[AsyncSession]) -> AsyncIterator[AsyncSession]:
    async with sessionmaker() as session:
        yield session


@pytest.fixture
def settings() -> Settings:
    return Settings(_env_file=None, api_token=SecretStr(TEST_TOKEN))


@pytest.fixture
def queue() -> FakeQueue:
    return FakeQueue()


def _build_client(
    sessionmaker: async_sessionmaker[AsyncSession],
    settings: Settings,
    token: str | None,
    queue: FakeQueue | None = None,
) -> AsyncClient:
    app = create_app()

    async def override_session() -> AsyncIterator[AsyncSession]:
        async with sessionmaker() as session:
            yield session

    fake_queue = queue or FakeQueue()
    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_queue] = lambda: fake_queue
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test", headers=headers)


@pytest.fixture
async def client(
    sessionmaker: async_sessionmaker[AsyncSession], settings: Settings, queue: FakeQueue
) -> AsyncIterator[AsyncClient]:
    """Authenticated client."""
    async with _build_client(sessionmaker, settings, TEST_TOKEN, queue) as client:
        yield client


@pytest.fixture
async def anon_client(
    sessionmaker: async_sessionmaker[AsyncSession], settings: Settings
) -> AsyncIterator[AsyncClient]:
    """Client without an Authorization header."""
    async with _build_client(sessionmaker, settings, None) as client:
        yield client
