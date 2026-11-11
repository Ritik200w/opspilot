from pathlib import Path

import pytest
from anthropic import APIStatusError, RateLimitError

import app.llm as llm
from app.llm import ClaudeClient, load_system_prompt
from tests.fakes import (
    FakeAnthropic,
    FakeMessage,
    bad_request_error,
    rate_limit_error,
    server_error,
)

pytestmark = pytest.mark.anyio


def _client(script: list[object], **kwargs: object) -> ClaudeClient:
    return ClaudeClient(
        api_key="test-key",
        model="claude-sonnet-5-5",
        backoff_base_seconds=0.0,  # no real sleeping in tests
        client=FakeAnthropic(script),  # type: ignore[arg-type]
        **kwargs,  # type: ignore[arg-type]
    )


async def test_complete_returns_text_and_usage() -> None:
    client = _client([FakeMessage("hello", input_tokens=11, output_tokens=7)])
    response = await client.complete(system="sys", user="usr")

    assert response.text == "hello"
    assert response.model == "claude-sonnet-5-5"
    assert response.input_tokens == 11
    assert response.output_tokens == 7


async def test_complete_passes_system_and_user() -> None:
    client = _client([FakeMessage("ok")])
    await client.complete(system="the system prompt", user="the user content")

    kwargs = client._client.messages.last_kwargs  # type: ignore[attr-defined]
    assert kwargs["system"] == "the system prompt"
    assert kwargs["messages"] == [{"role": "user", "content": "the user content"}]
    assert kwargs["model"] == "claude-sonnet-5-5"


async def test_retries_rate_limit_then_succeeds() -> None:
    client = _client([rate_limit_error(), FakeMessage("recovered")], max_retries=2)
    response = await client.complete(system="s", user="u")

    assert response.text == "recovered"
    assert client._client.messages.calls == 2  # type: ignore[attr-defined]


async def test_retries_server_error_then_succeeds() -> None:
    client = _client([server_error(), FakeMessage("recovered")], max_retries=2)
    response = await client.complete(system="s", user="u")

    assert response.text == "recovered"
    assert client._client.messages.calls == 2  # type: ignore[attr-defined]


async def test_gives_up_after_max_retries() -> None:
    client = _client([rate_limit_error(), rate_limit_error()], max_retries=1)
    with pytest.raises(RateLimitError):
        await client.complete(system="s", user="u")

    assert client._client.messages.calls == 2  # type: ignore[attr-defined] - 1 try + 1 retry


async def test_does_not_retry_client_error() -> None:
    client = _client([bad_request_error(), FakeMessage("unused")], max_retries=3)
    with pytest.raises(APIStatusError):
        await client.complete(system="s", user="u")

    assert client._client.messages.calls == 1  # type: ignore[attr-defined] - 400 is not retried


def test_system_prompt_marks_context_untrusted() -> None:
    prompt = load_system_prompt()
    assert "UNTRUSTED" in prompt
    assert "JSON" in prompt


def test_load_system_prompt_resolves_inside_package() -> None:
    # The worker's analysis path loads the prompt via load_system_prompt(); it must
    # resolve inside the installed package (app/prompts/), not the repo root, so it
    # works after `pip install .` into site-packages.
    assert llm._PROMPTS_DIR == Path(llm.__file__).resolve().parent / "prompts"
    prompt = load_system_prompt()
    assert prompt.strip()
    assert "triage assistant" in prompt.lower()
