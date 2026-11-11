import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Alert, Incident, IncidentStatus, Severity
from tests.conftest import FakeQueue
from tests.fixtures import load

pytestmark = pytest.mark.anyio

URL = "/webhooks/generic"


async def _incidents(session: AsyncSession) -> list[Incident]:
    return list(await session.scalars(select(Incident).order_by(Incident.created_at)))


async def _alert_count(session: AsyncSession) -> int:
    return await session.scalar(select(func.count()).select_from(Alert)) or 0


async def test_creates_incident_and_enqueues_analysis(
    client: AsyncClient, session: AsyncSession, queue: FakeQueue
) -> None:
    response = await client.post(URL, json=load("generic_alert.json"))

    assert response.status_code == 202
    body = response.json()
    incident_id = uuid.UUID(body["incident_ids"][0])
    assert body["alerts_stored"] == 1
    assert body["analysis_enqueued"] == [str(incident_id)]
    assert queue.enqueued == [incident_id]
    [incident] = await _incidents(session)
    assert incident.id == incident_id
    assert (incident.service, incident.severity) == ("orders", Severity.WARNING)
    assert incident.status is IncidentStatus.OPEN


async def test_duplicate_alert_is_skipped(
    client: AsyncClient, session: AsyncSession, queue: FakeQueue
) -> None:
    first = (await client.post(URL, json=load("generic_alert.json"))).json()

    second = await client.post(URL, json=load("generic_alert.json"))

    body = second.json()
    assert second.status_code == 202
    assert body["incident_ids"] == first["incident_ids"]
    assert body["duplicates_skipped"] == 1
    assert body["alerts_stored"] == 0
    assert body["analysis_enqueued"] == []
    assert len(queue.enqueued) == 1
    assert len(await _incidents(session)) == 1
    assert await _alert_count(session) == 1


async def test_same_problem_later_attaches_without_reanalysis(
    client: AsyncClient, session: AsyncSession, queue: FakeQueue
) -> None:
    await client.post(URL, json=load("generic_alert.json"))
    later = load("generic_alert.json") | {"starts_at": "2026-11-10T12:10:00Z"}

    body = (await client.post(URL, json=later)).json()

    assert body["alerts_stored"] == 1
    assert body["analysis_enqueued"] == []
    assert len(await _incidents(session)) == 1
    assert await _alert_count(session) == 2


async def test_escalation_raises_severity_and_reanalyzes(
    client: AsyncClient, session: AsyncSession, queue: FakeQueue
) -> None:
    await client.post(URL, json=load("generic_alert.json"))
    worse = load("generic_alert.json") | {
        "severity": "critical",
        "starts_at": "2026-11-10T12:05:00Z",
    }

    body = (await client.post(URL, json=worse)).json()

    [incident] = await _incidents(session)
    assert incident.severity is Severity.CRITICAL
    assert body["analysis_enqueued"] == [str(incident.id)]
    assert queue.enqueued == [incident.id, incident.id]


async def test_lower_severity_does_not_downgrade(
    client: AsyncClient, session: AsyncSession, queue: FakeQueue
) -> None:
    await client.post(URL, json=load("generic_alert.json") | {"severity": "critical"})
    milder = load("generic_alert.json") | {"severity": "info", "starts_at": "2026-11-10T12:05:00Z"}

    body = (await client.post(URL, json=milder)).json()

    [incident] = await _incidents(session)
    assert incident.severity is Severity.CRITICAL
    assert body["analysis_enqueued"] == []


async def test_resolved_alert_resolves_incident_and_next_firing_opens_new_one(
    client: AsyncClient, session: AsyncSession
) -> None:
    first = (await client.post(URL, json=load("generic_alert.json"))).json()

    resolved = await client.post(URL, json=load("generic_alert.json") | {"status": "resolved"})

    assert resolved.status_code == 202
    assert resolved.json()["incident_ids"] == first["incident_ids"]
    [incident] = await _incidents(session)
    await session.refresh(incident)
    assert incident.status is IncidentStatus.RESOLVED
    assert incident.resolved_at is not None
    # End this read transaction: tests share one in-memory SQLite connection with the app.
    await session.rollback()

    refire = load("generic_alert.json") | {"starts_at": "2026-11-10T14:00:00Z"}
    again = (await client.post(URL, json=refire)).json()

    assert again["incident_ids"] != first["incident_ids"]
    assert len(await _incidents(session)) == 2  # partial unique index allows it


async def test_resolved_without_open_incident_is_ignored(
    client: AsyncClient, session: AsyncSession, queue: FakeQueue
) -> None:
    response = await client.post(URL, json=load("generic_alert.json") | {"status": "resolved"})

    body = response.json()
    assert response.status_code == 202
    assert body["incident_ids"] == []
    assert body["resolved_ignored"] == 1
    assert await _incidents(session) == []
    assert queue.enqueued == []


async def test_enqueue_failure_still_accepts_and_reports(
    client: AsyncClient, session: AsyncSession, queue: FakeQueue
) -> None:
    queue.fail = True

    response = await client.post(URL, json=load("generic_alert.json"))

    body = response.json()
    assert response.status_code == 202
    assert body["analysis_enqueued"] == []
    assert body["analysis_enqueue_failed"] == body["incident_ids"]
    assert len(await _incidents(session)) == 1  # alert is not lost


@pytest.mark.parametrize(
    "change",
    [
        {"title": ""},
        {"severity": "urgent"},
        {"status": "pending"},
        {"unexpected": "field"},
        {"labels": {"k": 1}},
    ],
)
async def test_invalid_payload_is_rejected(client: AsyncClient, change: dict[str, object]) -> None:
    response = await client.post(URL, json=load("generic_alert.json") | change)

    assert response.status_code == 422


async def test_requires_token(anon_client: AsyncClient) -> None:
    response = await anon_client.post(URL, json=load("generic_alert.json"))

    assert response.status_code == 401
