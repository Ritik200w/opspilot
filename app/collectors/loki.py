"""Loki collector: recent ERROR/WARN log lines for a service.

Uses the range-query API over the incident window. Log lines are redacted before
they leave this collector, and the set is truncated to a safe size.
"""

import logging
from dataclasses import dataclass
from typing import Any

import httpx

from app.collectors.base import CollectedContext, CollectionTarget
from app.collectors.redact import redact_text
from app.models import ContextKind

logger = logging.getLogger(__name__)

# Matches python logging levels ERROR / WARNING (WARN is a prefix of WARNING).
_LEVEL_FILTER = "(?i)level=(ERROR|WARN)"


def _escape_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


@dataclass
class LokiCollector:
    """Collects recent error/warning logs for a service from a Loki server."""

    client: httpx.AsyncClient
    base_url: str
    max_lines: int = 200
    max_bytes: int = 64_000
    timeout_seconds: float = 10.0
    kind: ContextKind = ContextKind.LOGS
    name: str = "loki"

    def _logql(self, service: str) -> str:
        return f'{{service="{_escape_label(service)}"}} |~ "{_LEVEL_FILTER}"'

    async def collect(self, target: CollectionTarget) -> CollectedContext:
        logql = self._logql(target.service)
        # Ask for one extra line so we can tell whether Loki had more to give.
        limit = self.max_lines + 1
        response = await self.client.get(
            f"{self.base_url.rstrip('/')}/loki/api/v1/query_range",
            params={
                "query": logql,
                "start": _to_ns(target.window.start.timestamp()),
                "end": _to_ns(target.window.end.timestamp()),
                "limit": limit,
                "direction": "backward",  # newest first
            },
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("status") != "success":
            raise RuntimeError(f"loki query failed: {payload.get('error', 'unknown error')}")

        lines = _flatten_streams(payload.get("data", {}).get("result", []))
        kept, truncated = self._clamp(lines)
        return CollectedContext(
            kind=self.kind,
            query=logql,
            window=target.window,
            data={"service": target.service, "line_count": len(kept), "lines": kept},
            truncated=truncated,
        )

    def _clamp(self, lines: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], bool]:
        """Redact, then cap to max_lines and max_bytes. Returns (kept, truncated)."""
        truncated = len(lines) > self.max_lines
        kept: list[dict[str, Any]] = []
        total_bytes = 0
        for line in lines[: self.max_lines]:
            message = redact_text(line["line"])
            total_bytes += len(message.encode())
            if total_bytes > self.max_bytes:
                truncated = True
                break
            kept.append({"ts": line["ts"], "line": message})
        return kept, truncated


def _to_ns(unix_seconds: float) -> str:
    return str(int(unix_seconds * 1_000_000_000))


def _flatten_streams(result: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge Loki streams into one list of {ts, line}, newest first."""
    lines: list[dict[str, Any]] = []
    for stream in result:
        for ts, line in stream.get("values", []):
            lines.append({"ts": ts, "line": line})
    lines.sort(key=lambda item: item["ts"], reverse=True)
    return lines
