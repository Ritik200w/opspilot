"""Claude client for triage, built on the Anthropic SDK.

Wraps ``AsyncAnthropic`` with an explicit timeout and our own retry/backoff on
transient failures (rate limits, 5xx, connection/timeout errors). The SDK's own
retries are disabled so the behaviour here is the single source of truth and is
easy to test. The client never invents an answer: on failure it raises, and the
caller records the error.
"""

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path

from anthropic import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncAnthropic,
    RateLimitError,
)

from app.config import Settings

logger = logging.getLogger(__name__)

PROMPT_VERSION = "triage_v1"
# Prompts ship inside the package (app/prompts/) so they resolve whether the app
# runs from the repo or is pip-installed into site-packages.
_PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"

# Errors worth retrying: transient by nature. 4xx other than 429 are not retried.
_RETRYABLE_ERRORS = (RateLimitError, APITimeoutError, APIConnectionError)


@dataclass(frozen=True, slots=True)
class LLMResponse:
    """A completed Claude call: the raw text plus usage for the analyses row."""

    text: str
    model: str
    input_tokens: int | None
    output_tokens: int | None
    stop_reason: str | None


def load_system_prompt(version: str = PROMPT_VERSION) -> str:
    """Read a versioned system prompt from the ``prompts/`` directory."""
    return (_PROMPTS_DIR / f"{version}.md").read_text(encoding="utf-8")


def _is_retryable(exc: Exception) -> bool:
    if isinstance(exc, _RETRYABLE_ERRORS):
        return True
    # Server-side failures (500, 502, 503, ...); client errors (4xx) are not retried.
    return isinstance(exc, APIStatusError) and exc.status_code >= 500


def _extract_text(message: object) -> str:
    """Concatenate the text blocks of a Messages API response."""
    parts: list[str] = []
    for block in getattr(message, "content", None) or []:
        if getattr(block, "type", None) == "text" or hasattr(block, "text"):
            text = getattr(block, "text", None)
            if isinstance(text, str):
                parts.append(text)
    return "".join(parts)


class ClaudeClient:
    """Minimal async wrapper around the Anthropic Messages API for triage."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        timeout_seconds: float = 30.0,
        max_retries: int = 2,
        max_tokens: int = 1024,
        backoff_base_seconds: float = 0.5,
        client: AsyncAnthropic | None = None,
    ) -> None:
        self._client = client or AsyncAnthropic(
            api_key=api_key,
            timeout=timeout_seconds,
            max_retries=0,  # we handle retries ourselves
        )
        self._model = model
        self._max_tokens = max_tokens
        self._max_retries = max_retries
        self._backoff_base_seconds = backoff_base_seconds

    @classmethod
    def from_settings(
        cls, settings: Settings, *, client: AsyncAnthropic | None = None
    ) -> "ClaudeClient":
        return cls(
            api_key=settings.anthropic_api_key.get_secret_value(),
            model=settings.anthropic_model,
            timeout_seconds=settings.anthropic_timeout_seconds,
            max_retries=settings.anthropic_max_retries,
            max_tokens=settings.anthropic_max_tokens,
            client=client,
        )

    @property
    def model(self) -> str:
        return self._model

    async def complete(self, *, system: str, user: str) -> LLMResponse:
        """Call Claude once (with retries on transient errors) and return the text.

        Raises the underlying Anthropic error if every attempt fails.
        """
        attempt = 0
        while True:
            try:
                message = await self._client.messages.create(
                    model=self._model,
                    max_tokens=self._max_tokens,
                    system=system,
                    messages=[{"role": "user", "content": user}],
                )
                usage = getattr(message, "usage", None)
                return LLMResponse(
                    text=_extract_text(message),
                    model=getattr(message, "model", None) or self._model,
                    input_tokens=getattr(usage, "input_tokens", None),
                    output_tokens=getattr(usage, "output_tokens", None),
                    stop_reason=getattr(message, "stop_reason", None),
                )
            except Exception as exc:  # noqa: BLE001 - classified by _is_retryable below
                if _is_retryable(exc) and attempt < self._max_retries:
                    delay = self._backoff_base_seconds * (2**attempt)
                    logger.warning(
                        "claude call failed (attempt %d/%d), retrying in %.2fs: %s",
                        attempt + 1,
                        self._max_retries + 1,
                        delay,
                        exc,
                    )
                    await asyncio.sleep(delay)
                    attempt += 1
                    continue
                raise
