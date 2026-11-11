"""arq worker. Run with: arq app.worker.WorkerSettings"""

import logging
import uuid
from typing import Any, ClassVar

import httpx
from arq.connections import RedisSettings
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.collectors import (
    Collector,
    LokiCollector,
    PrometheusCollector,
    build_window,
    collect_context,
)
from app.config import Settings, get_settings
from app.db import get_sessionmaker
from app.llm import ClaudeClient
from app.models import Incident
from app.queue import redis_settings
from app.services.analyze import analyze_incident_context

logger = logging.getLogger(__name__)


def build_collectors(client: httpx.AsyncClient, settings: Settings) -> list[Collector]:
    """The default collector set, sharing one HTTP client."""
    return [
        PrometheusCollector(
            client=client,
            base_url=settings.prometheus_url,
            step_seconds=settings.collector_step_seconds,
            max_points=settings.collector_max_metric_points,
            timeout_seconds=settings.collector_timeout_seconds,
        ),
        LokiCollector(
            client=client,
            base_url=settings.loki_url,
            max_lines=settings.collector_max_log_lines,
            max_bytes=settings.collector_max_log_bytes,
            timeout_seconds=settings.collector_timeout_seconds,
        ),
    ]


def _collectors(ctx: dict[str, Any], settings: Settings) -> list[Collector]:
    # Tests inject collectors directly; the running worker builds them from its client.
    injected = ctx.get("collectors")
    if injected is not None:
        return injected
    return build_collectors(ctx["http_client"], settings)


def _claude_client(ctx: dict[str, Any], settings: Settings) -> ClaudeClient:
    # Tests inject a mocked client; the running worker builds one from settings.
    injected = ctx.get("claude_client")
    if injected is not None:
        return injected
    return ClaudeClient.from_settings(settings)


async def analyze_incident(ctx: dict[str, Any], incident_id: str) -> str:
    """Gather context (metrics + logs) for the incident, then run Claude triage.

    Step 4b: collectors run and their results are stored as context_snapshots.
    Step 5: Claude analyzes the incident; the run is stored in analyses and, on
    success, a fix_proposal is created. (Slack posting is step 6.)
    """
    settings = get_settings()
    sessionmaker: async_sessionmaker[AsyncSession] = ctx.get("sessionmaker") or get_sessionmaker()

    async with sessionmaker() as session:
        incident = await session.get(Incident, uuid.UUID(incident_id))
        if incident is None:
            logger.warning("analyze_incident: incident %s not found", incident_id)
            return f"incident {incident_id} not found"

        window = build_window(
            incident,
            before_minutes=settings.collector_window_before_minutes,
            after_minutes=settings.collector_window_after_minutes,
        )
        snapshots = await collect_context(
            session, incident, _collectors(ctx, settings), window=window
        )
        await session.commit()

        outcome = await analyze_incident_context(
            session, incident, _claude_client(ctx, settings), settings
        )

    logger.info(
        "analyze_incident for incident %s: %d context snapshots, analysis ok=%s",
        incident_id,
        len(snapshots),
        outcome.ok,
    )
    status = "analyzed" if outcome.ok else f"failed ({outcome.error})"
    return f"incident {incident_id}: {len(snapshots)} snapshots, triage {status}"


async def on_startup(ctx: dict[str, Any]) -> None:
    settings = get_settings()
    ctx["sessionmaker"] = get_sessionmaker()
    ctx["http_client"] = httpx.AsyncClient(timeout=settings.collector_timeout_seconds)
    ctx["claude_client"] = ClaudeClient.from_settings(settings)


async def on_shutdown(ctx: dict[str, Any]) -> None:
    client: httpx.AsyncClient | None = ctx.get("http_client")
    if client is not None:
        await client.aclose()


class WorkerSettings:
    functions: ClassVar[list[Any]] = [analyze_incident]
    redis_settings: ClassVar[RedisSettings] = redis_settings()
    on_startup = staticmethod(on_startup)
    on_shutdown = staticmethod(on_shutdown)
    max_tries = 3
