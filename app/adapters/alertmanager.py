from app.adapters.common import make_dedup_key, parse_severity, stable_hash, to_utc
from app.models.enums import AlertSource, AlertStatus
from app.schemas.alerts import AlertmanagerAlert, AlertmanagerPayload, NormalizedAlert

UNKNOWN_SERVICE = "unknown"


def alertmanager_dedup_key(group_key: str) -> str:
    # groupKey can be long; hash it so the indexed column stays small.
    return make_dedup_key("alertmanager", group_key)


def from_alertmanager(payload: AlertmanagerPayload) -> list[NormalizedAlert]:
    """One NormalizedAlert per alert in the group; the whole group shares one dedup key."""
    dedup_key = alertmanager_dedup_key(payload.group_key)
    return [_convert(alert, payload, dedup_key) for alert in payload.alerts]


def _service(labels: dict[str, str]) -> str:
    return labels.get("service") or labels.get("job") or labels.get("app") or UNKNOWN_SERVICE


def _title(labels: dict[str, str], annotations: dict[str, str]) -> str:
    return annotations.get("summary") or labels.get("alertname") or "Alertmanager alert"


def _fingerprint(alert: AlertmanagerAlert) -> str:
    if alert.fingerprint:
        return alert.fingerprint
    return stable_hash(*(f"{k}={v}" for k, v in sorted(alert.labels.items())))


def _convert(
    alert: AlertmanagerAlert, payload: AlertmanagerPayload, dedup_key: str
) -> NormalizedAlert:
    labels = payload.common_labels | alert.labels
    annotations = payload.common_annotations | alert.annotations
    status = AlertStatus(alert.status)
    # Firing alerts carry a placeholder endsAt (year 1 or a timeout); only resolved ones are real.
    ends_at = to_utc(alert.ends_at) if status is AlertStatus.RESOLVED and alert.ends_at else None
    return NormalizedAlert(
        source=AlertSource.ALERTMANAGER,
        dedup_key=dedup_key,
        fingerprint=_fingerprint(alert),
        status=status,
        severity=parse_severity(labels.get("severity")),
        service=_service(labels),
        title=_title(labels, annotations),
        starts_at=to_utc(alert.starts_at),
        ends_at=ends_at,
        labels=labels,
        annotations=annotations,
        raw_payload=alert.model_dump(mode="json", by_alias=True),
    )
