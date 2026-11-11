from datetime import UTC, datetime, timedelta, timezone

import pytest

from app.adapters.alertmanager import alertmanager_dedup_key, from_alertmanager
from app.adapters.common import parse_severity, to_utc
from app.adapters.generic import from_generic, generic_dedup_key
from app.models import AlertSource, AlertStatus, Severity
from app.schemas.alerts import AlertmanagerPayload, GenericAlertIn
from tests.fixtures import load

NOW = datetime(2026, 11, 10, 13, 0, tzinfo=UTC)


def test_generic_adapter_normalizes_fixture() -> None:
    alert = from_generic(GenericAlertIn.model_validate(load("generic_alert.json")), now=NOW)

    assert alert.source is AlertSource.GENERIC
    assert alert.status is AlertStatus.FIRING
    assert alert.severity is Severity.WARNING
    assert (alert.service, alert.title) == ("orders", "Order API latency above 2s")
    assert alert.dedup_key == generic_dedup_key("orders", "Order API latency above 2s")
    assert alert.dedup_key.startswith("generic:")
    assert alert.fingerprint == alert.dedup_key
    assert alert.starts_at == datetime(2026, 11, 10, 12, 0, tzinfo=UTC)
    assert alert.ends_at is None
    assert alert.annotations == {"description": "p95 latency on /orders is 2.4s for 5 minutes"}
    assert alert.labels == {"env": "local", "team": "payments"}


def test_generic_adapter_defaults_and_resolved() -> None:
    payload = GenericAlertIn(title="t", service="s", severity=Severity.INFO, status="resolved")

    alert = from_generic(payload, now=NOW)

    assert alert.starts_at == NOW
    assert alert.ends_at == NOW
    assert alert.annotations == {}


def test_generic_dedup_key_depends_on_service_and_title_only() -> None:
    assert generic_dedup_key("a", "b") == generic_dedup_key("a", "b")
    assert generic_dedup_key("ab", "c") != generic_dedup_key("a", "bc")


def test_alertmanager_adapter_normalizes_each_alert_in_group() -> None:
    payload = AlertmanagerPayload.model_validate(load("alertmanager_firing.json"))

    alerts = from_alertmanager(payload)

    assert len(alerts) == 2
    assert {a.dedup_key for a in alerts} == {alertmanager_dedup_key(payload.group_key)}
    first = alerts[0]
    assert first.source is AlertSource.ALERTMANAGER
    assert first.fingerprint == "a1b2c3d4e5f60001"
    assert first.severity is Severity.CRITICAL
    assert (first.service, first.title) == ("checkout", "Checkout 5xx rate above 5%")
    assert first.ends_at is None  # placeholder "0001-01-01" endsAt is dropped
    assert first.labels["instance"] == "checkout-1:8000"
    assert first.raw_payload["generatorURL"].startswith("http://prometheus")


def test_alertmanager_adapter_resolved_keeps_ends_at() -> None:
    payload = AlertmanagerPayload.model_validate(load("alertmanager_resolved.json"))

    alert = from_alertmanager(payload)[0]

    assert alert.status is AlertStatus.RESOLVED
    assert alert.ends_at == datetime(2026, 11, 10, 12, 20, tzinfo=UTC)


def test_alertmanager_adapter_fallbacks() -> None:
    raw = load("alertmanager_firing.json")
    raw["commonLabels"] = {}
    raw["commonAnnotations"] = {}
    raw["alerts"] = [raw["alerts"][0]]
    alert_raw = raw["alerts"][0]
    alert_raw["labels"] = {"alertname": "DiskFull", "job": "node", "severity": "bogus"}
    alert_raw["annotations"] = {}
    del alert_raw["fingerprint"]

    alert = from_alertmanager(AlertmanagerPayload.model_validate(raw))[0]

    assert alert.service == "node"  # falls back to job
    assert alert.title == "DiskFull"  # falls back to alertname
    assert alert.severity is Severity.WARNING  # unknown severity -> warning
    assert len(alert.fingerprint) == 64  # derived from labels


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("critical", Severity.CRITICAL),
        ("PAGE", Severity.CRITICAL),
        (" warning ", Severity.WARNING),
        ("info", Severity.INFO),
        ("weird", Severity.WARNING),
        (None, Severity.WARNING),
    ],
)
def test_parse_severity(raw: str | None, expected: Severity) -> None:
    assert parse_severity(raw) is expected


def test_to_utc() -> None:
    plus_two = timezone(timedelta(hours=2))

    assert to_utc(datetime(2026, 1, 1, 12)) == datetime(2026, 1, 1, 12, tzinfo=UTC)
    assert to_utc(datetime(2026, 1, 1, 12, tzinfo=plus_two)).hour == 10
