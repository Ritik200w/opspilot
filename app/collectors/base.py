"""Collector protocol and the runner that stores results as context_snapshots.

A collector queries one source (Prometheus, Loki, ...) for the time window
around an incident and returns a :class:`CollectedContext`. The runner turns each
result into a ``context_snapshots`` row. A collector that fails is recorded (its
error is stored on the snapshot's ``data``) but never crashes the job: triage
should still run on whatever context was gathered.
"""

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.common import to_utc
from app.models import ContextKind, ContextSnapshot, Incident

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class CollectionWindow:
    """The time range a collector queries, around the incident."""

    start: datetime
    end: datetime


@dataclass(frozen=True, slots=True)
class CollectionTarget:
    """What to collect: one service over one window."""

    service: str
    window: CollectionWindow


@dataclass(frozen=True, slots=True)
class CollectedContext:
    """A collector's result, mapped 1:1 to a context_snapshots row."""

    kind: ContextKind
    query: str
    window: CollectionWindow
    data: dict[str, Any] = field(default_factory=dict)
    truncated: bool = False
    error: str | None = None


class Collector(Protocol):
    """Queries one source for an incident's context window."""

    kind: ContextKind
    name: str

    async def collect(self, target: CollectionTarget) -> CollectedContext: ...


def build_window(
    incident: Incident,
    *,
    before_minutes: int,
    after_minutes: int,
    now: datetime | None = None,
) -> CollectionWindow:
    """Window around the incident: a lookback before it opened up to ``after`` later,
    never into the future."""
    now = now or datetime.now(UTC)
    anchor = to_utc(incident.opened_at)
    start = anchor - timedelta(minutes=before_minutes)
    end = min(anchor + timedelta(minutes=after_minutes), now)
    if end <= start:
        end = anchor
    return CollectionWindow(start=start, end=end)


def _snapshot_data(result: CollectedContext) -> dict[str, Any]:
    data = dict(result.data)
    if result.error is not None:
        data["error"] = result.error
    return data


async def _run_one(collector: Collector, target: CollectionTarget) -> CollectedContext:
    try:
        return await collector.collect(target)
    except Exception as exc:  # noqa: BLE001 - one bad collector must not sink the job
        logger.exception("collector %s failed for service %s", collector.name, target.service)
        return CollectedContext(
            kind=collector.kind,
            query="",
            window=target.window,
            error=f"{type(exc).__name__}: {exc}",
        )


async def collect_context(
    session: AsyncSession,
    incident: Incident,
    collectors: list[Collector],
    *,
    window: CollectionWindow,
) -> list[ContextSnapshot]:
    """Run each collector and persist one snapshot per collector. Failures are
    recorded on the snapshot, not raised. Flushes; the caller commits."""
    target = CollectionTarget(service=incident.service, window=window)
    snapshots: list[ContextSnapshot] = []
    for collector in collectors:
        result = await _run_one(collector, target)
        snapshot = ContextSnapshot(
            incident_id=incident.id,
            kind=result.kind,
            query=result.query,
            window_start=result.window.start,
            window_end=result.window.end,
            data=_snapshot_data(result),
            truncated=result.truncated,
        )
        session.add(snapshot)
        snapshots.append(snapshot)
    await session.flush()
    return snapshots
