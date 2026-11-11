"""Job queue (arq on Redis). The API only enqueues; app/worker.py runs the jobs."""

import asyncio
import logging
import uuid
from typing import Protocol

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings
from fastapi import Request

from app.config import get_settings

logger = logging.getLogger(__name__)

ANALYZE_INCIDENT = "analyze_incident"


class JobQueue(Protocol):
    async def enqueue_analysis(self, incident_id: uuid.UUID) -> None: ...


class ArqJobQueue:
    def __init__(self, pool: ArqRedis) -> None:
        self._pool = pool

    async def enqueue_analysis(self, incident_id: uuid.UUID) -> None:
        await self._pool.enqueue_job(ANALYZE_INCIDENT, str(incident_id))

    async def close(self) -> None:
        await self._pool.aclose()


def redis_settings() -> RedisSettings:
    return RedisSettings.from_dsn(get_settings().redis_url)


_connect_lock = asyncio.Lock()


async def get_queue(request: Request) -> JobQueue:
    """FastAPI dependency. Connects lazily so the API starts even if Redis is briefly down."""
    state = request.app.state
    if getattr(state, "job_queue", None) is None:
        async with _connect_lock:
            if getattr(state, "job_queue", None) is None:
                state.job_queue = ArqJobQueue(await create_pool(redis_settings()))
    return state.job_queue


async def enqueue_analyses(
    queue: JobQueue, incident_ids: list[uuid.UUID]
) -> tuple[list[uuid.UUID], list[uuid.UUID]]:
    """Returns (enqueued, failed). Failures are logged, not raised: the alerts are already
    committed, so failing the webhook would only make the sender retry into a duplicate."""
    enqueued: list[uuid.UUID] = []
    failed: list[uuid.UUID] = []
    for incident_id in incident_ids:
        try:
            await queue.enqueue_analysis(incident_id)
        except Exception:
            logger.exception("Failed to enqueue analysis for incident %s", incident_id)
            failed.append(incident_id)
        else:
            enqueued.append(incident_id)
    return enqueued, failed
