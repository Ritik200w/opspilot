import uuid
from datetime import timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import IncidentStatus, Severity
from tests.factories import T0, make_alert, make_analysis, make_fix, make_incident

pytestmark = pytest.mark.anyio


async def test_list_empty(client: AsyncClient) -> None:
    response = await client.get("/incidents")

    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0, "limit": 20, "offset": 0}


async def test_list_newest_first_with_paging(client: AsyncClient, session: AsyncSession) -> None:
    incidents = [
        make_incident(title=f"inc-{i}", opened_at=T0 + timedelta(minutes=i)) for i in range(5)
    ]
    session.add_all(incidents)
    await session.commit()

    response = await client.get("/incidents", params={"limit": 2, "offset": 1})

    body = response.json()
    assert response.status_code == 200
    assert body["total"] == 5
    assert (body["limit"], body["offset"]) == (2, 1)
    assert [item["title"] for item in body["items"]] == ["inc-3", "inc-2"]


@pytest.mark.parametrize(
    ("params", "expected_titles"),
    [
        ({"status": "resolved"}, {"resolved-one"}),
        ({"service": "payments"}, {"payments-one"}),
        ({"severity": "warning"}, {"payments-one"}),
        ({"status": "open", "service": "checkout"}, {"checkout-one"}),
    ],
)
async def test_list_filters(
    client: AsyncClient,
    session: AsyncSession,
    params: dict[str, str],
    expected_titles: set[str],
) -> None:
    session.add_all(
        [
            make_incident(title="checkout-one"),
            make_incident(title="payments-one", service="payments", severity=Severity.WARNING),
            make_incident(title="resolved-one", status=IncidentStatus.RESOLVED),
        ]
    )
    await session.commit()

    response = await client.get("/incidents", params=params)

    body = response.json()
    assert {item["title"] for item in body["items"]} == expected_titles
    assert body["total"] == len(expected_titles)


@pytest.mark.parametrize(
    "params",
    [{"limit": 0}, {"limit": 101}, {"offset": -1}, {"status": "bogus"}, {"severity": "high"}],
)
async def test_list_rejects_bad_params(client: AsyncClient, params: dict[str, object]) -> None:
    response = await client.get("/incidents", params=params)

    assert response.status_code == 422


async def test_detail_includes_alerts_latest_analysis_and_its_fixes(
    client: AsyncClient, session: AsyncSession
) -> None:
    incident = make_incident()
    session.add(incident)
    await session.flush()
    old = make_analysis(incident, summary="old guess")
    new = make_analysis(incident, summary="new guess", created_at=T0 + timedelta(minutes=5))
    session.add_all([make_alert(incident), old, new])
    await session.flush()
    session.add_all([make_fix(old, title="old fix"), make_fix(new, title="new fix")])
    await session.commit()

    response = await client.get(f"/incidents/{incident.id}")

    body = response.json()
    assert response.status_code == 200
    assert body["id"] == str(incident.id)
    assert [a["fingerprint"] for a in body["alerts"]] == ["fp-1"]
    assert "raw_payload" not in body["alerts"][0]
    assert body["latest_analysis"]["summary"] == "new guess"
    assert body["latest_analysis"]["confidence"] == 0.8
    assert [f["title"] for f in body["fix_proposals"]] == ["new fix"]
    assert body["fix_proposals"][0]["status"] == "proposed"


async def test_detail_without_analysis(client: AsyncClient, session: AsyncSession) -> None:
    incident = make_incident()
    session.add(incident)
    await session.commit()

    body = (await client.get(f"/incidents/{incident.id}")).json()

    assert body["latest_analysis"] is None
    assert body["fix_proposals"] == []
    assert body["alerts"] == []


async def test_detail_not_found(client: AsyncClient) -> None:
    response = await client.get(f"/incidents/{uuid.uuid4()}")

    assert response.status_code == 404


async def test_detail_invalid_id(client: AsyncClient) -> None:
    response = await client.get("/incidents/not-a-uuid")

    assert response.status_code == 422
