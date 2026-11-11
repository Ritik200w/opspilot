"""Ingest-service cases that are hard to hit through HTTP."""

import uuid
from dataclasses import replace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.adapters.generic import from_generic
from app.models import Incident
from app.queue import enqueue_analyses
from app.schemas.alerts import GenericAlertIn, NormalizedAlert
from app.services import ingest
from app.worker import analyze_incident
from tests.conftest import FakeQueue
from tests.factories import make_incident
from tests.fixtures import load

pytestmark = pytest.mark.anyio


def _alert() -> NormalizedAlert:
    return from_generic(GenericAlertIn.model_validate(load("generic_alert.json")))


async def test_concurrent_create_falls_back_to_existing_incident(
    sessionmaker: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Simulate a race: another request inserts the open incident after our lookup."""
    alert = _alert()
    async with sessionmaker() as other:
        winner = make_incident(dedup_key=alert.dedup_key)
        other.add(winner)
        await other.commit()

    real_find = ingest._find_open_incident
    calls = {"n": 0}

    async def stale_first_lookup(session: AsyncSession, key: str) -> Incident | None:
        calls["n"] += 1
        return None if calls["n"] == 1 else await real_find(session, key)

    monkeypatch.setattr(ingest, "_find_open_incident", stale_first_lookup)

    async with sessionmaker() as session:
        result = await ingest.ingest_alerts(session, [alert])
        incidents = list(await session.scalars(select(Incident)))

    assert result.incident_ids == [winner.id]
    assert result.to_analyze == []  # the winner's request already enqueued it
    assert result.stored == 1
    assert len(incidents) == 1


async def test_multiple_alerts_in_one_call_share_incident(session: AsyncSession) -> None:
    alert = _alert()
    later = replace(alert, starts_at=alert.starts_at.replace(minute=30), fingerprint="other")

    result = await ingest.ingest_alerts(session, [alert, later])

    assert len(result.incident_ids) == 1
    assert result.stored == 2
    assert result.to_analyze == result.incident_ids


class _FailsFor(FakeQueue):
    def __init__(self, bad: uuid.UUID) -> None:
        super().__init__()
        self.bad = bad

    async def enqueue_analysis(self, incident_id: uuid.UUID) -> None:
        if incident_id == self.bad:
            raise ConnectionError("redis down")
        await super().enqueue_analysis(incident_id)


async def test_enqueue_analyses_splits_success_and_failure() -> None:
    good, bad = uuid.uuid4(), uuid.uuid4()
    queue = _FailsFor(bad)

    enqueued, failed = await enqueue_analyses(queue, [good, bad])

    assert enqueued == [good]
    assert failed == [bad]
    assert queue.enqueued == [good]


async def test_worker_skips_missing_incident(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    ctx = {"sessionmaker": sessionmaker, "collectors": []}
    result = await analyze_incident(ctx, str(uuid.uuid4()))
    assert "not found" in result
