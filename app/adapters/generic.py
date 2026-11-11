from datetime import UTC, datetime

from app.adapters.common import make_dedup_key, to_utc
from app.models.enums import AlertSource, AlertStatus
from app.schemas.alerts import GenericAlertIn, NormalizedAlert


def generic_dedup_key(service: str, title: str) -> str:
    return make_dedup_key("generic", service, title)


def from_generic(payload: GenericAlertIn, now: datetime | None = None) -> NormalizedAlert:
    dedup_key = generic_dedup_key(payload.service, payload.title)
    starts_at = to_utc(payload.starts_at) if payload.starts_at else (now or datetime.now(UTC))
    annotations = {"description": payload.description} if payload.description else {}
    resolved = payload.status is AlertStatus.RESOLVED
    return NormalizedAlert(
        source=AlertSource.GENERIC,
        dedup_key=dedup_key,
        fingerprint=payload.fingerprint or dedup_key,
        status=payload.status,
        severity=payload.severity,
        service=payload.service,
        title=payload.title,
        starts_at=starts_at,
        ends_at=(now or datetime.now(UTC)) if resolved else None,
        labels=dict(payload.labels),
        annotations=annotations,
        raw_payload=payload.model_dump(mode="json"),
    )
