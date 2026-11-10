import uuid
from dataclasses import dataclass, field

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Analysis, FixProposal, Incident, IncidentStatus, Severity


@dataclass(frozen=True)
class IncidentFilters:
    status: IncidentStatus | None = None
    service: str | None = None
    severity: Severity | None = None


@dataclass(frozen=True)
class IncidentDetailData:
    incident: Incident
    latest_analysis: Analysis | None
    fix_proposals: list[FixProposal] = field(default_factory=list)


def _conditions(filters: IncidentFilters) -> list[ColumnElement[bool]]:
    conditions: list[ColumnElement[bool]] = []
    if filters.status is not None:
        conditions.append(Incident.status == filters.status)
    if filters.service is not None:
        conditions.append(Incident.service == filters.service)
    if filters.severity is not None:
        conditions.append(Incident.severity == filters.severity)
    return conditions


async def list_incidents(
    session: AsyncSession, filters: IncidentFilters, limit: int, offset: int
) -> tuple[list[Incident], int]:
    """Newest first. Returns (page of incidents, total matching)."""
    conditions = _conditions(filters)
    total = await session.scalar(select(func.count()).select_from(Incident).where(*conditions))
    rows = await session.scalars(
        select(Incident)
        .where(*conditions)
        .order_by(Incident.opened_at.desc(), Incident.id)
        .limit(limit)
        .offset(offset)
    )
    return list(rows), total or 0


async def _latest_analysis(session: AsyncSession, incident_id: uuid.UUID) -> Analysis | None:
    return await session.scalar(
        select(Analysis)
        .where(Analysis.incident_id == incident_id)
        .order_by(Analysis.created_at.desc())
        .limit(1)
    )


async def _proposals_for(session: AsyncSession, analysis_id: uuid.UUID) -> list[FixProposal]:
    rows = await session.scalars(
        select(FixProposal)
        .where(FixProposal.analysis_id == analysis_id)
        .order_by(FixProposal.created_at)
    )
    return list(rows)


async def get_incident_detail(
    session: AsyncSession, incident_id: uuid.UUID
) -> IncidentDetailData | None:
    incident = await session.scalar(
        select(Incident).where(Incident.id == incident_id).options(selectinload(Incident.alerts))
    )
    if incident is None:
        return None
    analysis = await _latest_analysis(session, incident_id)
    proposals = await _proposals_for(session, analysis.id) if analysis else []
    return IncidentDetailData(incident, analysis, proposals)
