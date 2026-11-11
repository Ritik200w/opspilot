"""arq worker. Run with: arq app.worker.WorkerSettings"""

import logging
from typing import Any, ClassVar

from arq.connections import RedisSettings

from app.queue import redis_settings

logger = logging.getLogger(__name__)


async def analyze_incident(ctx: dict[str, Any], incident_id: str) -> str:
    """Stub. Steps 4-5 replace this with collect context -> Claude -> store -> Slack."""
    logger.info("analyze_incident (stub) for incident %s", incident_id)
    return f"stub: would analyze {incident_id}"


class WorkerSettings:
    functions: ClassVar[list[Any]] = [analyze_incident]
    redis_settings: ClassVar[RedisSettings] = redis_settings()
    max_tries = 3
