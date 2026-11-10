"""Small builders for ORM rows used in tests. Override any field via kwargs."""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from app.models import (
    Alert,
    AlertSource,
    AlertStatus,
    Analysis,
    FixProposal,
    FixRisk,
    Incident,
    IncidentStatus,
    Severity,
)

T0 = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)


def make_incident(**overrides: object) -> Incident:
    fields: dict[str, object] = {
        "dedup_key": f"key-{uuid.uuid4()}",
        "title": "High error rate",
        "service": "checkout",
        "severity": Severity.CRITICAL,
        "status": IncidentStatus.OPEN,
        "opened_at": T0,
    }
    return Incident(**(fields | overrides))


def make_alert(incident: Incident, **overrides: object) -> Alert:
    fields: dict[str, object] = {
        "incident_id": incident.id,
        "source": AlertSource.ALERTMANAGER,
        "fingerprint": "fp-1",
        "status": AlertStatus.FIRING,
        "severity": incident.severity,
        "service": incident.service,
        "title": incident.title,
        "labels": {"alertname": "HighErrorRate", "service": incident.service},
        "annotations": {"summary": "5xx rate above 5%"},
        "starts_at": T0,
        "raw_payload": {"secret": "should-not-be-exposed"},
        "received_at": T0,
    }
    return Alert(**(fields | overrides))


def make_analysis(incident: Incident, **overrides: object) -> Analysis:
    fields: dict[str, object] = {
        "incident_id": incident.id,
        "model": "claude-opus-5-5",
        "prompt_version": "triage_v1",
        "summary": "Checkout returns 500s",
        "root_cause": "DB connection pool exhausted",
        "confidence": Decimal("0.800"),
        "evidence": ["pool_wait_seconds spiked at 12:01"],
        "created_at": T0,
    }
    return Analysis(**(fields | overrides))


def make_fix(analysis: Analysis, **overrides: object) -> FixProposal:
    fields: dict[str, object] = {
        "analysis_id": analysis.id,
        "incident_id": analysis.incident_id,
        "title": "Raise pool size",
        "steps": ["Set DB_POOL_SIZE=20", "Redeploy checkout"],
        "risk": FixRisk.LOW,
        "created_at": T0,
    }
    return FixProposal(**(fields | overrides))
