import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.models.enums import (
    AlertSource,
    AlertStatus,
    FixRisk,
    FixStatus,
    IncidentStatus,
    Severity,
)


class _ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class AlertOut(_ORMModel):
    id: uuid.UUID
    source: AlertSource
    fingerprint: str
    status: AlertStatus
    severity: Severity
    service: str
    title: str
    labels: dict[str, str]
    annotations: dict[str, str]
    starts_at: datetime
    ends_at: datetime | None
    received_at: datetime


class AnalysisOut(_ORMModel):
    id: uuid.UUID
    model: str
    prompt_version: str
    summary: str | None
    root_cause: str | None
    confidence: float | None
    evidence: list[Any]
    input_tokens: int | None
    output_tokens: int | None
    latency_ms: int | None
    error: str | None
    created_at: datetime


class FixProposalOut(_ORMModel):
    id: uuid.UUID
    analysis_id: uuid.UUID
    title: str
    steps: list[str]
    risk: FixRisk
    status: FixStatus
    decided_by: str | None
    decided_at: datetime | None
    decision_note: str | None
    created_at: datetime


class IncidentOut(_ORMModel):
    id: uuid.UUID
    dedup_key: str
    title: str
    service: str
    severity: Severity
    status: IncidentStatus
    opened_at: datetime
    resolved_at: datetime | None
    created_at: datetime
    updated_at: datetime


class IncidentDetail(IncidentOut):
    alerts: list[AlertOut]
    latest_analysis: AnalysisOut | None
    fix_proposals: list[FixProposalOut]  # proposals from the latest analysis


class IncidentPage(BaseModel):
    items: list[IncidentOut]
    total: int
    limit: int
    offset: int


class ReanalyzeAccepted(BaseModel):
    incident_id: uuid.UUID
    status: str = "enqueued"
