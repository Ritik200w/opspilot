"""Consistency checks across docker-compose, the observability configs and the OpsPilot app.

These can't prove Prometheus/Alertmanager accept the files (that needs promtool/amtool in
Docker), but they catch the wiring mistakes that silently break the alert path."""

from pathlib import Path
from typing import Any

import pytest
import yaml

from app.adapters.common import parse_severity
from app.main import create_app
from app.models import Severity

ROOT = Path(__file__).resolve().parents[1]
OBS = ROOT / "observability"


def _yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text())


@pytest.fixture(scope="module")
def compose() -> dict[str, Any]:
    return _yaml(ROOT / "docker-compose.yml")


@pytest.fixture(scope="module")
def high_error_rate() -> dict[str, Any]:
    rules = _yaml(OBS / "alert_rules.yml")["groups"][0]["rules"]
    return next(r for r in rules if r["alert"] == "HighErrorRate")


def test_high_error_rate_rule(high_error_rate: dict[str, Any]) -> None:
    assert "http_requests_total" in high_error_rate["expr"]
    assert "by (service)" in high_error_rate["expr"]
    assert parse_severity(high_error_rate["labels"]["severity"]) is Severity.CRITICAL
    # summary becomes the incident title, so it must not contain the changing $value
    assert "$value" not in high_error_rate["annotations"]["summary"]


def test_alertmanager_posts_to_opspilot_webhook_with_secret_token(compose: dict[str, Any]) -> None:
    config = _yaml(OBS / "alertmanager.yml")
    [webhook] = config["receivers"][0]["webhook_configs"]
    routes = set(create_app().openapi()["paths"])

    assert webhook["url"] == "http://api:8000/webhooks/alertmanager"
    assert "/webhooks/alertmanager" in routes
    assert webhook["send_resolved"] is True
    assert webhook["http_config"]["authorization"]["type"] == "Bearer"
    secret_name = Path(webhook["http_config"]["authorization"]["credentials_file"]).name
    assert secret_name in compose["services"]["alertmanager"]["secrets"]
    assert compose["secrets"][secret_name] == {"environment": "API_TOKEN"}
    assert {"alertname", "service"} <= set(config["route"]["group_by"])


def test_prometheus_scrapes_demo_app_with_matching_service_label(compose: dict[str, Any]) -> None:
    config = _yaml(OBS / "prometheus.yml")
    [static] = config["scrape_configs"][0]["static_configs"]

    assert static["targets"] == ["demo-app:8000"]
    assert static["labels"]["service"] == "demo-app"
    assert "demo-app" in compose["services"]
    assert config["alerting"]["alertmanagers"][0]["static_configs"][0]["targets"] == [
        "alertmanager:9093"
    ]


def test_prometheus_rule_file_is_mounted(compose: dict[str, Any]) -> None:
    [rule_file] = _yaml(OBS / "prometheus.yml")["rule_files"]
    mounts = compose["services"]["prometheus"]["volumes"]

    assert any(m.endswith(f":{rule_file}:ro") for m in mounts)


def test_alloy_ships_logs_for_labelled_services(compose: dict[str, Any]) -> None:
    alloy = (OBS / "config.alloy").read_text()
    assert 'values = ["opspilot.logs=true"]' in alloy
    assert "http://loki:3100/loki/api/v1/push" in alloy
    for name in ("api", "worker", "demo-app"):
        assert compose["services"][name]["labels"] == {"opspilot.logs": "true"}, name


def test_every_service_has_a_memory_limit_and_pinned_image(compose: dict[str, Any]) -> None:
    for name, service in compose["services"].items():
        assert "mem_limit" in service, f"{name} has no mem_limit"
        image = service.get("image")
        if image:
            assert ":" in image and not image.endswith(":latest"), f"{name} image not pinned"
