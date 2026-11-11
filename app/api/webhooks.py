from typing import Annotated

from fastapi import APIRouter, Depends

from app.adapters.alertmanager import from_alertmanager
from app.adapters.generic import from_generic
from app.api.deps import SessionDep, require_api_token
from app.queue import JobQueue, enqueue_analyses, get_queue
from app.schemas.alerts import (
    AlertmanagerPayload,
    GenericAlertIn,
    NormalizedAlert,
    WebhookAccepted,
)
from app.services.ingest import ingest_alerts

router = APIRouter(prefix="/webhooks", tags=["webhooks"], dependencies=[Depends(require_api_token)])

QueueDep = Annotated[JobQueue, Depends(get_queue)]


@router.post("/generic", status_code=202)
async def generic_webhook(
    payload: GenericAlertIn, session: SessionDep, queue: QueueDep
) -> WebhookAccepted:
    return await _accept(session, queue, [from_generic(payload)])


@router.post("/alertmanager", status_code=202)
async def alertmanager_webhook(
    payload: AlertmanagerPayload, session: SessionDep, queue: QueueDep
) -> WebhookAccepted:
    return await _accept(session, queue, from_alertmanager(payload))


async def _accept(
    session: SessionDep, queue: JobQueue, alerts: list[NormalizedAlert]
) -> WebhookAccepted:
    result = await ingest_alerts(session, alerts)  # commits before we enqueue
    enqueued, failed = await enqueue_analyses(queue, result.to_analyze)
    return WebhookAccepted(
        incident_ids=result.incident_ids,
        alerts_stored=result.stored,
        duplicates_skipped=result.duplicates,
        resolved_ignored=result.resolved_ignored,
        analysis_enqueued=enqueued,
        analysis_enqueue_failed=failed,
    )
