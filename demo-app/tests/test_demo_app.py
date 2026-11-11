import pytest

pytest.importorskip("prometheus_client", reason="pip install -r demo-app/requirements.txt")

from demo_app import MAX_MEMORY_MB, create_app  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


def _metric_value(client: TestClient, sample: str) -> float:
    for line in client.get("/metrics").text.splitlines():
        if line.startswith(sample + " "):
            return float(line.split()[-1])
    return 0.0


ORDERS_OK = 'http_requests_total{method="GET",path="/orders",status="200"}'
ORDERS_500 = 'http_requests_total{method="GET",path="/orders",status="500"}'


def test_orders_ok_and_counted(client: TestClient) -> None:
    response = client.get("/orders")

    assert response.status_code == 200
    assert response.json()["orders"]
    assert _metric_value(client, ORDERS_OK) == 1


def test_metrics_and_health_are_not_counted(client: TestClient) -> None:
    client.get("/health")
    client.get("/metrics")

    text = client.get("/metrics").text

    assert 'path="/metrics"' not in text
    assert 'path="/health"' not in text
    assert "http_request_duration_seconds" in text


def test_error_chaos_switches_on_and_off(client: TestClient) -> None:
    assert client.post("/chaos/errors", params={"rate": 1}).json()["error_rate"] == 1

    assert client.get("/orders").status_code == 500
    assert _metric_value(client, ORDERS_500) == 1
    assert _metric_value(client, 'demo_chaos_active{mode="errors"}') == 1

    client.delete("/chaos/errors")

    assert client.get("/orders").status_code == 200
    assert _metric_value(client, 'demo_chaos_active{mode="errors"}') == 0


def test_error_chaos_logs_an_error(client: TestClient, caplog: pytest.LogCaptureFixture) -> None:
    client.post("/chaos/errors", params={"rate": 1})

    client.get("/orders")

    assert any(
        r.levelname == "ERROR" and "connection pool exhausted" in r.getMessage()
        for r in caplog.records
    )


def test_latency_chaos(client: TestClient) -> None:
    client.post("/chaos/latency", params={"ms": 80})

    response = client.get("/orders")

    assert response.status_code == 200
    assert client.get("/chaos").json()["latency_ms"] == 80
    assert (
        _metric_value(
            client, 'http_request_duration_seconds_bucket{le="0.05",method="GET",path="/orders"}'
        )
        == 0
    )  # took at least 80 ms, so it is not in the <=50 ms bucket
    client.delete("/chaos/latency")
    assert client.get("/chaos").json()["latency_ms"] == 0


def test_memory_chaos_holds_and_releases(client: TestClient) -> None:
    state = client.post("/chaos/memory", params={"mb": 2}).json()

    assert state["memory_mb"] == 2
    assert _metric_value(client, "demo_chaos_ballast_bytes") == 2 * 1024 * 1024

    assert client.delete("/chaos/memory").json()["memory_mb"] == 0
    assert _metric_value(client, "demo_chaos_ballast_bytes") == 0


@pytest.mark.parametrize(
    ("path", "params"),
    [
        ("/chaos/errors", {"rate": 0}),
        ("/chaos/errors", {"rate": 1.5}),
        ("/chaos/latency", {"ms": 999_999}),
        ("/chaos/memory", {"mb": MAX_MEMORY_MB + 1}),
    ],
)
def test_chaos_limits(client: TestClient, path: str, params: dict[str, float]) -> None:
    assert client.post(path, params=params).status_code == 422
