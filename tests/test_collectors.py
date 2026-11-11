from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
import respx
from httpx import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.collectors import (
    CollectionTarget,
    CollectionWindow,
    LokiCollector,
    PrometheusCollector,
    build_window,
    collect_context,
)
from app.collectors.base import CollectedContext
from app.models import ContextKind, ContextSnapshot
from app.worker import analyze_incident
from tests.factories import T0, make_incident

pytestmark = pytest.mark.anyio

PROM = "http://prometheus:9090"
LOKI = "http://loki:3100"

PROM_RANGE = f"{PROM}/api/v1/query_range"
LOKI_RANGE = f"{LOKI}/loki/api/v1/query_range"


def _window() -> CollectionWindow:
    return CollectionWindow(start=T0, end=T0 + timedelta(minutes=5))


def _target(service: str = "checkout") -> CollectionTarget:
    return CollectionTarget(service=service, window=_window())


def _matrix(values: list[list[Any]]) -> dict[str, Any]:
    return {
        "status": "success",
        "data": {
            "resultType": "matrix",
            "result": [{"metric": {"service": "checkout"}, "values": values}],
        },
    }


def _streams(values: list[list[str]]) -> dict[str, Any]:
    return {
        "status": "success",
        "data": {
            "resultType": "streams",
            "result": [{"stream": {"service": "checkout"}, "values": values}],
        },
    }


# --------------------------------------------------------------------- Prometheus


async def test_prometheus_collector_parses_each_metric() -> None:
    with respx.mock:
        route = respx.get(PROM_RANGE).mock(
            return_value=Response(200, json=_matrix([[1700000000, "0.1"], [1700000015, "0.2"]]))
        )
        async with httpx.AsyncClient() as client:
            collector = PrometheusCollector(client=client, base_url=PROM)
            result = await collector.collect(_target())

    assert route.call_count == 3  # error rate, request rate, latency
    assert result.kind is ContextKind.METRICS
    assert result.truncated is False
    metrics = result.data["metrics"]
    assert set(metrics) == {"error_rate", "request_rate", "latency_p95_seconds"}
    assert metrics["request_rate"]["series"][0]["values"][0] == [1700000000, "0.1"]
    # The service is filtered on and the error-rate query targets 5xx responses.
    assert 'service="checkout"' in metrics["error_rate"]["query"]
    assert 'status=~"5.."' in metrics["error_rate"]["query"]


async def test_prometheus_collector_truncates_long_series() -> None:
    values = [[1700000000 + i, str(i)] for i in range(10)]
    with respx.mock:
        respx.get(PROM_RANGE).mock(return_value=Response(200, json=_matrix(values)))
        async with httpx.AsyncClient() as client:
            collector = PrometheusCollector(client=client, base_url=PROM, max_points=3)
            result = await collector.collect(_target())

    series = result.data["metrics"]["request_rate"]["series"][0]["values"]
    assert len(series) == 3
    assert series[-1] == [1700000009, "9"]  # most recent points kept
    assert result.truncated is True


async def test_prometheus_collector_raises_on_error_status() -> None:
    with respx.mock:
        respx.get(PROM_RANGE).mock(
            return_value=Response(200, json={"status": "error", "error": "bad query"})
        )
        async with httpx.AsyncClient() as client:
            collector = PrometheusCollector(client=client, base_url=PROM)
            with pytest.raises(RuntimeError, match="bad query"):
                await collector.collect(_target())


async def test_prometheus_collector_raises_on_http_error() -> None:
    with respx.mock:
        respx.get(PROM_RANGE).mock(return_value=Response(503))
        async with httpx.AsyncClient() as client:
            collector = PrometheusCollector(client=client, base_url=PROM)
            with pytest.raises(httpx.HTTPStatusError):
                await collector.collect(_target())


# --------------------------------------------------------------------- Loki


async def test_loki_collector_redacts_and_orders_newest_first() -> None:
    values = [
        ["1699999998000000000", "level=WARNING contacting user alice@example.com"],
        ["1699999999000000000", 'level=ERROR msg="db pool exhausted" password=hunter2'],
    ]
    with respx.mock:
        route = respx.get(LOKI_RANGE).mock(return_value=Response(200, json=_streams(values)))
        async with httpx.AsyncClient() as client:
            collector = LokiCollector(client=client, base_url=LOKI)
            result = await collector.collect(_target())

    assert result.kind is ContextKind.LOGS
    assert result.truncated is False
    assert result.data["line_count"] == 2
    lines = result.data["lines"]
    assert lines[0]["ts"] == "1699999999000000000"  # newest first
    joined = " ".join(item["line"] for item in lines)
    assert "hunter2" not in joined
    assert "alice@example.com" not in joined
    assert "db pool exhausted" in joined  # non-secret content kept
    sent_query = route.calls.last.request.url.params["query"]
    assert 'service="checkout"' in sent_query
    assert "ERROR|WARN" in sent_query


async def test_loki_collector_truncates_by_line_count() -> None:
    values = [[str(1700000000000000000 + i), f"level=ERROR i={i}"] for i in range(6)]
    with respx.mock:
        respx.get(LOKI_RANGE).mock(return_value=Response(200, json=_streams(values)))
        async with httpx.AsyncClient() as client:
            collector = LokiCollector(client=client, base_url=LOKI, max_lines=3)
            result = await collector.collect(_target())

    assert result.data["line_count"] == 3
    assert result.truncated is True


async def test_loki_collector_truncates_by_bytes() -> None:
    big = "level=ERROR " + "x" * 100
    values = [[str(1700000000000000000 + i), big] for i in range(5)]
    with respx.mock:
        respx.get(LOKI_RANGE).mock(return_value=Response(200, json=_streams(values)))
        async with httpx.AsyncClient() as client:
            collector = LokiCollector(client=client, base_url=LOKI, max_lines=100, max_bytes=150)
            result = await collector.collect(_target())

    assert result.truncated is True
    assert 0 < result.data["line_count"] < 5


async def test_loki_collector_raises_on_error_status() -> None:
    with respx.mock:
        respx.get(LOKI_RANGE).mock(
            return_value=Response(200, json={"status": "error", "error": "parse error"})
        )
        async with httpx.AsyncClient() as client:
            collector = LokiCollector(client=client, base_url=LOKI)
            with pytest.raises(RuntimeError, match="parse error"):
                await collector.collect(_target())


# --------------------------------------------------------------------- Runner


class _BoomCollector:
    kind = ContextKind.METRICS
    name = "boom"

    async def collect(self, target: CollectionTarget) -> CollectedContext:
        raise RuntimeError("prometheus unreachable")


class _OkCollector:
    kind = ContextKind.LOGS
    name = "ok"

    async def collect(self, target: CollectionTarget) -> CollectedContext:
        return CollectedContext(kind=self.kind, query="q", window=target.window, data={"lines": []})


async def test_collect_context_records_failure_without_crashing(session: AsyncSession) -> None:
    incident = make_incident(service="checkout")
    session.add(incident)
    await session.flush()

    snapshots = await collect_context(
        session, incident, [_BoomCollector(), _OkCollector()], window=_window()
    )

    assert len(snapshots) == 2
    failed = next(s for s in snapshots if s.kind is ContextKind.METRICS)
    assert "prometheus unreachable" in failed.data["error"]
    assert failed.truncated is False
    ok = next(s for s in snapshots if s.kind is ContextKind.LOGS)
    assert "error" not in ok.data


def test_build_window_clamps_to_now() -> None:
    incident = make_incident(opened_at=T0)
    window = build_window(incident, before_minutes=15, after_minutes=5, now=T0)

    assert window.start == T0 - timedelta(minutes=15)
    assert window.end == T0  # "after" is clamped: never into the future


# --------------------------------------------------------------------- Worker wiring


async def test_analyze_incident_collects_and_stores(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async with sessionmaker() as setup:
        incident = make_incident(service="checkout", opened_at=datetime.now(UTC))
        setup.add(incident)
        await setup.commit()
        incident_id = incident.id

    with respx.mock:
        respx.get(PROM_RANGE).mock(return_value=Response(200, json=_matrix([[1700000000, "0.1"]])))
        respx.get(LOKI_RANGE).mock(
            return_value=Response(200, json=_streams([["1700000000000000000", "level=ERROR boom"]]))
        )
        async with httpx.AsyncClient() as client:
            ctx = {"sessionmaker": sessionmaker, "http_client": client}
            result = await analyze_incident(ctx, str(incident_id))

    assert "2 context snapshots" in result
    async with sessionmaker() as check:
        rows = (
            await check.scalars(
                select(ContextSnapshot).where(ContextSnapshot.incident_id == incident_id)
            )
        ).all()
    assert {row.kind for row in rows} == {ContextKind.METRICS, ContextKind.LOGS}
