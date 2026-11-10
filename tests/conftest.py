from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
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

TEST_TOKEN = "test-token-123"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    """Fresh in-memory SQLite DB per test, schema built from the models."""
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
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


def _build_client(
    sessionmaker: async_sessionmaker[AsyncSession], settings: Settings, token: str | None
) -> AsyncClient:
    app = create_app()

    async def override_session() -> AsyncIterator[AsyncSession]:
        async with sessionmaker() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_settings] = lambda: settings
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test", headers=headers)


@pytest.fixture
async def client(
    sessionmaker: async_sessionmaker[AsyncSession], settings: Settings
) -> AsyncIterator[AsyncClient]:
    """Authenticated client."""
    async with _build_client(sessionmaker, settings, TEST_TOKEN) as client:
        yield client


@pytest.fixture
async def anon_client(
    sessionmaker: async_sessionmaker[AsyncSession], settings: Settings
) -> AsyncIterator[AsyncClient]:
    """Client without an Authorization header."""
    async with _build_client(sessionmaker, settings, None) as client:
        yield client
