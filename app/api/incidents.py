import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import SessionDep, require_api_token
from app.models import IncidentStatus, Severity
from app.schemas.incident import (
    AlertOut,
    AnalysisOut,
    FixProposalOut,
    IncidentDetail,
    IncidentOut,
    IncidentPage,
)
from app.services import incidents as incident_service
from app.services.incidents import IncidentDetailData, IncidentFilters

router = APIRouter(
    prefix="/incidents", tags=["incidents"], dependencies=[Depends(require_api_token)]
)


@router.get("")
async def list_incidents(
    session: SessionDep,
    status: IncidentStatus | None = None,
    service: Annotated[str | None, Query(max_length=200)] = None,
    severity: Severity | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> IncidentPage:
    filters = IncidentFilters(status=status, service=service, severity=severity)
    rows, total = await incident_service.list_incidents(session, filters, limit, offset)
    items = [IncidentOut.model_validate(row) for row in rows]
    return IncidentPage(items=items, total=total, limit=limit, offset=offset)


@router.get("/{incident_id}")
async def get_incident(incident_id: uuid.UUID, session: SessionDep) -> IncidentDetail:
    detail = await incident_service.get_incident_detail(session, incident_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    return _to_detail(detail)


def _to_detail(data: IncidentDetailData) -> IncidentDetail:
    base = IncidentOut.model_validate(data.incident).model_dump()
    return IncidentDetail(
        **base,
        alerts=[AlertOut.model_validate(a) for a in data.incident.alerts],
        latest_analysis=AnalysisOut.model_validate(data.latest_analysis)
        if data.latest_analysis
        else None,
        fix_proposals=[FixProposalOut.model_validate(p) for p in data.fix_proposals],
    )
