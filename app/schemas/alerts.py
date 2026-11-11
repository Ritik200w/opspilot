"""Inbound webhook payloads and the single normalized alert format the ingest service uses."""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from app.models.enums import AlertSource, AlertStatus, Severity


@dataclass(frozen=True, slots=True)
class NormalizedAlert:
    """Source-independent alert. Every adapter produces this; ingest only consumes this."""

    source: AlertSource
    dedup_key: str
    fingerprint: str
    status: AlertStatus
    severity: Severity
    service: str
    title: str
    starts_at: datetime
    ends_at: datetime | None = None
    labels: dict[str, str] = field(default_factory=dict)
    annotations: dict[str, str] = field(default_factory=dict)
    raw_payload: dict[str, Any] = field(default_factory=dict)


class GenericAlertIn(BaseModel):
    """OpsPilot's own simple alert format."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=500)
    service: str = Field(min_length=1, max_length=200)
    severity: Severity
    status: AlertStatus = AlertStatus.FIRING
    description: str | None = Field(default=None, max_length=10_000)
    labels: dict[str, str] = Field(default_factory=dict)
    starts_at: datetime | None = None
    fingerprint: str | None = Field(default=None, max_length=200)


class _AlertmanagerModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class AlertmanagerAlert(_AlertmanagerModel):
    model_config = ConfigDict(extra="allow")  # keep unknown fields in raw_payload

    status: Literal["firing", "resolved"]
    labels: dict[str, str]
    annotations: dict[str, str] = Field(default_factory=dict)
    starts_at: datetime
    ends_at: datetime | None = None
    generator_url: str | None = Field(default=None, alias="generatorURL")
    fingerprint: str | None = None


class AlertmanagerPayload(_AlertmanagerModel):
    """Alertmanager webhook payload, version 4."""

    version: Literal["4"]
    group_key: str = Field(min_length=1)
    truncated_alerts: int = 0
    status: Literal["firing", "resolved"]
    receiver: str
    group_labels: dict[str, str] = Field(default_factory=dict)
    common_labels: dict[str, str] = Field(default_factory=dict)
    common_annotations: dict[str, str] = Field(default_factory=dict)
    external_url: str | None = Field(default=None, alias="externalURL")
    alerts: list[AlertmanagerAlert] = Field(min_length=1)


class WebhookAccepted(BaseModel):
    incident_ids: list[uuid.UUID]
    alerts_stored: int
    duplicates_skipped: int
    resolved_ignored: int  # resolved alerts with no open incident to attach to
    analysis_enqueued: list[uuid.UUID]
    analysis_enqueue_failed: list[uuid.UUID]
