import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Alert, AlertStatus, Incident, IncidentStatus, Severity
from tests.conftest import FakeQueue
from tests.fixtures import load

pytestmark = pytest.mark.anyio

URL = "/webhooks/alertmanager"


async def _only_incident(session: AsyncSession) -> Incident:
    [incident] = list(await session.scalars(select(Incident)))
    await session.refresh(incident)
    return incident


async def _alert_count(session: AsyncSession) -> int:
    return await session.scalar(select(func.count()).select_from(Alert)) or 0


async def test_firing_group_becomes_one_incident(
    client: AsyncClient, session: AsyncSession, queue: FakeQueue
) -> None:
    response = await client.post(URL, json=load("alertmanager_firing.json"))

    body = response.json()
    assert response.status_code == 202
    assert body["alerts_stored"] == 2
    incident = await _only_incident(session)
    assert body["incident_ids"] == [str(incident.id)]
    assert queue.enqueued == [incident.id]
    assert incident.title == "Checkout 5xx rate above 5%"
    assert (incident.service, incident.severity) == ("checkout", Severity.CRITICAL)
    assert await _alert_count(session) == 2


async def test_repeated_notification_is_deduplicated(
    client: AsyncClient, session: AsyncSession, queue: FakeQueue
) -> None:
    await client.post(URL, json=load("alertmanager_firing.json"))

    body = (await client.post(URL, json=load("alertmanager_firing.json"))).json()

    assert body["duplicates_skipped"] == 2
    assert body["alerts_stored"] == 0
    assert body["analysis_enqueued"] == []
    assert len(queue.enqueued) == 1
    assert await _alert_count(session) == 2


async def test_resolved_group_resolves_incident(
    client: AsyncClient, session: AsyncSession, queue: FakeQueue
) -> None:
    await client.post(URL, json=load("alertmanager_firing.json"))

    response = await client.post(URL, json=load("alertmanager_resolved.json"))

    body = response.json()
    assert response.status_code == 202
    assert body["alerts_stored"] == 2
    assert body["analysis_enqueued"] == []
    incident = await _only_incident(session)
    assert incident.status is IncidentStatus.RESOLVED
    assert incident.resolved_at is not None
    assert incident.resolved_at.replace(tzinfo=None).isoformat() == "2026-11-10T12:21:00"
    statuses = set(await session.scalars(select(Alert.status)))
    assert statuses == {AlertStatus.FIRING, AlertStatus.RESOLVED}


async def test_partial_resolution_keeps_incident_open(
    client: AsyncClient, session: AsyncSession
) -> None:
    await client.post(URL, json=load("alertmanager_firing.json"))
    partial = load("alertmanager_resolved.json")
    partial["status"] = "firing"
    partial["alerts"] = partial["alerts"][:1]  # only checkout-1 recovered

    await client.post(URL, json=partial)

    incident = await _only_incident(session)
    assert incident.status is IncidentStatus.OPEN
    assert incident.resolved_at is None


async def test_resolved_before_any_firing_is_ignored(
    client: AsyncClient, session: AsyncSession
) -> None:
    body = (await client.post(URL, json=load("alertmanager_resolved.json"))).json()

    assert body["resolved_ignored"] == 2
    assert body["incident_ids"] == []
    assert list(await session.scalars(select(Incident))) == []


@pytest.mark.parametrize(
    "mutate",
    [
        lambda p: p.update(version="3"),
        lambda p: p.update(alerts=[]),
        lambda p: p.pop("groupKey"),
        lambda p: p["alerts"][0].update(status="pending"),
    ],
)
async def test_invalid_payload_is_rejected(client: AsyncClient, mutate: object) -> None:
    payload = load("alertmanager_firing.json")
    mutate(payload)  # type: ignore[operator]

    response = await client.post(URL, json=payload)

    assert response.status_code == 422


async def test_requires_token(anon_client: AsyncClient) -> None:
    response = await anon_client.post(URL, json=load("alertmanager_firing.json"))

    assert response.status_code == 401
