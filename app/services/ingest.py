"""Store normalized alerts and group them into incidents.

Rules:
- One open (non-resolved) incident per dedup_key, enforced by the partial unique index.
- Firing alert: attach to the open incident, or create one. New incident -> analyze.
- Incident severity is the highest seen across its alerts. Escalation -> re-analyze.
- Exact repeats (same fingerprint, status and starts_at) are skipped, e.g. Alertmanager's
  repeat_interval re-sends.
- Resolved alert: attach to the open incident. The incident resolves once the latest status of
  every fingerprint on it is resolved. A resolved alert with no open incident is ignored.
"""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import exists, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.common import to_utc
from app.models import Alert, AlertStatus, Incident, IncidentStatus
from app.models.enums import is_more_severe
from app.schemas.alerts import NormalizedAlert


@dataclass
class IngestResult:
    incident_ids: list[uuid.UUID] = field(default_factory=list)
    to_analyze: list[uuid.UUID] = field(default_factory=list)
    stored: int = 0
    duplicates: int = 0
    resolved_ignored: int = 0

    def touch(self, incident_id: uuid.UUID) -> None:
        if incident_id not in self.incident_ids:
            self.incident_ids.append(incident_id)

    def mark_for_analysis(self, incident_id: uuid.UUID) -> None:
        self.touch(incident_id)
        if incident_id not in self.to_analyze:
            self.to_analyze.append(incident_id)


async def ingest_alerts(session: AsyncSession, alerts: list[NormalizedAlert]) -> IngestResult:
    """Process alerts in order and commit once. Enqueueing is the caller's job (after commit)."""
    result = IngestResult()
    for alert in alerts:
        if alert.status is AlertStatus.RESOLVED:
            await _ingest_resolved(session, alert, result)
        else:
            await _ingest_firing(session, alert, result)
    await session.commit()
    return result


async def _ingest_firing(
    session: AsyncSession, alert: NormalizedAlert, result: IngestResult
) -> None:
    incident, created = await _get_or_create_open_incident(session, alert)
    if created:
        result.mark_for_analysis(incident.id)
    elif await _is_duplicate(session, incident, alert):
        result.duplicates += 1
        result.touch(incident.id)
        return
    elif is_more_severe(alert.severity, incident.severity):
        incident.severity = alert.severity
        result.mark_for_analysis(incident.id)
    _add_alert(session, incident, alert)
    result.stored += 1
    result.touch(incident.id)


async def _ingest_resolved(
    session: AsyncSession, alert: NormalizedAlert, result: IngestResult
) -> None:
    incident = await _find_open_incident(session, alert.dedup_key)
    if incident is None:
        result.resolved_ignored += 1
        return
    result.touch(incident.id)
    if await _is_duplicate(session, incident, alert):
        result.duplicates += 1
        return
    _add_alert(session, incident, alert)
    result.stored += 1
    if await _all_fingerprints_resolved(session, incident.id):
        incident.status = IncidentStatus.RESOLVED
        incident.resolved_at = alert.ends_at or datetime.now(UTC)


async def _find_open_incident(session: AsyncSession, dedup_key: str) -> Incident | None:
    return await session.scalar(
        select(Incident).where(
            Incident.dedup_key == dedup_key, Incident.status != IncidentStatus.RESOLVED
        )
    )


async def _get_or_create_open_incident(
    session: AsyncSession, alert: NormalizedAlert
) -> tuple[Incident, bool]:
    """Returns (incident, created). Handles a concurrent insert via the partial unique index."""
    existing = await _find_open_incident(session, alert.dedup_key)
    if existing is not None:
        return existing, False
    incident = Incident(
        dedup_key=alert.dedup_key,
        title=alert.title,
        service=alert.service,
        severity=alert.severity,
        status=IncidentStatus.OPEN,
        opened_at=alert.starts_at,
    )
    try:
        async with session.begin_nested():
            session.add(incident)
    except IntegrityError:
        # Another request created the open incident between our SELECT and INSERT.
        winner = await _find_open_incident(session, alert.dedup_key)
        if winner is None:
            raise
        return winner, False
    return incident, True


async def _is_duplicate(session: AsyncSession, incident: Incident, alert: NormalizedAlert) -> bool:
    found = await session.scalar(
        select(
            exists().where(
                Alert.incident_id == incident.id,
                Alert.fingerprint == alert.fingerprint,
                Alert.status == alert.status,
                Alert.starts_at == to_utc(alert.starts_at),
            )
        )
    )
    return bool(found)


async def _all_fingerprints_resolved(session: AsyncSession, incident_id: uuid.UUID) -> bool:
    rows = await session.execute(
        select(Alert.fingerprint, Alert.status)
        .where(Alert.incident_id == incident_id)
        .order_by(Alert.received_at)
    )
    latest: dict[str, AlertStatus] = {}
    for fingerprint, status in rows:
        latest[fingerprint] = status
    return bool(latest) and all(s is AlertStatus.RESOLVED for s in latest.values())


def _add_alert(session: AsyncSession, incident: Incident, alert: NormalizedAlert) -> None:
    session.add(
        Alert(
            incident_id=incident.id,
            source=alert.source,
            fingerprint=alert.fingerprint,
            status=alert.status,
            severity=alert.severity,
            service=alert.service,
            title=alert.title,
            labels=alert.labels,
            annotations=alert.annotations,
            starts_at=alert.starts_at,
            ends_at=alert.ends_at,
            raw_payload=alert.raw_payload,
            # Set in Python (not now()) so alerts within one transaction keep their order.
            received_at=datetime.now(UTC),
        )
    )
