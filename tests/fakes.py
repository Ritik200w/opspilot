"""Fakes for the Anthropic client, so triage tests never hit the network."""

import json
from typing import Any

import httpx
from anthropic import APIStatusError, InternalServerError, RateLimitError

VALID_TRIAGE_OUTPUT: dict[str, Any] = {
    "root_cause": "Checkout DB connection pool exhausted under load",
    "confidence": 0.8,
    "evidence": [
        "error_rate for checkout spiked to ~0.4 at 12:01",
        "logs show 'db pool exhausted'",
    ],
    "severity_suggestion": "critical",
    "fix": {
        "title": "Raise the checkout DB connection pool size",
        "steps": ["Set DB_POOL_SIZE=20", "Redeploy checkout", "Watch error_rate recover"],
        "risk": "low",
    },
}

VALID_TRIAGE_JSON = json.dumps(VALID_TRIAGE_OUTPUT)


class _TextBlock:
    def __init__(self, text: str) -> None:
        self.type = "text"
        self.text = text


class _Usage:
    def __init__(self, input_tokens: int, output_tokens: int) -> None:
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class FakeMessage:
    """Stands in for anthropic.types.Message in tests."""

    def __init__(
        self,
        text: str,
        *,
        model: str = "claude-sonnet-5-5",
        input_tokens: int = 123,
        output_tokens: int = 45,
        stop_reason: str | None = "end_turn",
    ) -> None:
        self.content = [_TextBlock(text)]
        self.model = model
        self.usage = _Usage(input_tokens, output_tokens)
        self.stop_reason = stop_reason


class FakeMessages:
    """messages.create that replays a scripted sequence of results/exceptions."""

    def __init__(self, script: list[Any]) -> None:
        self._script = list(script)
        self.calls = 0
        self.last_kwargs: dict[str, Any] | None = None

    async def create(self, **kwargs: Any) -> Any:  # noqa: ANN401 - mirrors the SDK
        self.calls += 1
        self.last_kwargs = kwargs
        item = self._script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class FakeAnthropic:
    """Duck-typed stand-in for AsyncAnthropic."""

    def __init__(self, script: list[Any]) -> None:
        self.messages = FakeMessages(script)


def _request() -> httpx.Request:
    return httpx.Request("POST", "https://api.anthropic.com/v1/messages")


def rate_limit_error() -> RateLimitError:
    return RateLimitError(
        "rate limited", response=httpx.Response(429, request=_request()), body=None
    )


def server_error() -> InternalServerError:
    return InternalServerError("boom", response=httpx.Response(503, request=_request()), body=None)


def bad_request_error() -> APIStatusError:
    return APIStatusError(
        "bad request", response=httpx.Response(400, request=_request()), body=None
    )
