import pytest
from httpx import AsyncClient
from pydantic import SecretStr

from app.api.deps import tokens_match
from app.config import Settings
from tests.conftest import _build_client

pytestmark = pytest.mark.anyio


def test_tokens_match() -> None:
    assert tokens_match("abc", "abc")
    assert not tokens_match("abc", "abd")
    assert not tokens_match("", "abc")
    assert tokens_match("tökén", "tökén")  # non-ASCII must not raise


async def test_missing_token_is_rejected(anon_client: AsyncClient) -> None:
    response = await anon_client.get("/incidents")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


async def test_wrong_token_is_rejected(anon_client: AsyncClient) -> None:
    response = await anon_client.get("/incidents", headers={"Authorization": "Bearer nope"})

    assert response.status_code == 401


async def test_wrong_scheme_is_rejected(anon_client: AsyncClient) -> None:
    response = await anon_client.get("/incidents", headers={"Authorization": "Basic dGVzdA=="})

    assert response.status_code == 401


async def test_unconfigured_token_fails_closed(sessionmaker) -> None:  # noqa: ANN001
    settings = Settings(_env_file=None, api_token=SecretStr(""))
    async with _build_client(sessionmaker, settings, "anything") as client:
        response = await client.get("/incidents")

    assert response.status_code == 503


async def test_health_needs_no_token(anon_client: AsyncClient) -> None:
    response = await anon_client.get("/health")

    assert response.status_code == 200
