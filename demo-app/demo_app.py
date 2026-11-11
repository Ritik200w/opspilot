"""Demo service that OpsPilot watches. It has chaos switches so we can break it on purpose.

Chaos (no auth: local demo only):
  POST   /chaos/errors?rate=0.5   fail that share of /orders requests with a 500
  POST   /chaos/latency?ms=1500   add delay to every /orders request
  POST   /chaos/memory?mb=32      hold that much extra memory (capped by CHAOS_MAX_MEMORY_MB)
  DELETE /chaos/{errors,latency,memory}   switch the mode off
  GET    /chaos                   current state
"""

import asyncio
import logging
import os
import random
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query, Request, Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    ProcessCollector,
    generate_latest,
)

SERVICE = os.getenv("SERVICE_NAME", "demo-app")
MAX_MEMORY_MB = int(os.getenv("CHAOS_MAX_MEMORY_MB", "64"))
MAX_LATENCY_MS = 10_000
MB = 1024 * 1024

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format='ts=%(asctime)s level=%(levelname)s logger=%(name)s msg="%(message)s"',
)
logger = logging.getLogger(SERVICE)


@dataclass
class Chaos:
    error_rate: float = 0.0
    latency_ms: int = 0
    ballast: list[bytearray] = field(default_factory=list)

    @property
    def memory_mb(self) -> int:
        return len(self.ballast)

    def snapshot(self) -> dict[str, float | int]:
        return {
            "error_rate": self.error_rate,
            "latency_ms": self.latency_ms,
            "memory_mb": self.memory_mb,
        }


class Metrics:
    def __init__(self, registry: CollectorRegistry) -> None:
        self.requests = Counter(
            "http_requests",
            "HTTP requests handled",
            ["method", "path", "status"],
            registry=registry,
        )
        self.duration = Histogram(
            "http_request_duration_seconds",
            "HTTP request duration",
            ["method", "path"],
            buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10),
            registry=registry,
        )
        self.chaos = Gauge(
            "demo_chaos_active", "1 while a chaos mode is on", ["mode"], registry=registry
        )
        self.ballast = Gauge(
            "demo_chaos_ballast_bytes", "Extra memory held by chaos", registry=registry
        )


def _is_tracked(path: str) -> bool:
    """Only business traffic counts toward request metrics (keeps the error ratio honest)."""
    return path not in {"/metrics", "/health"} and not path.startswith("/chaos")


def _add_metrics_middleware(app: FastAPI, metrics: Metrics) -> None:
    @app.middleware("http")
    async def record(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if not _is_tracked(request.url.path):
            return await call_next(request)
        start = time.perf_counter()
        status = 500  # stays 500 if the handler raises unexpectedly
        try:
            response = await call_next(request)
            status = response.status_code
            return response
        finally:
            path = getattr(
                request.scope.get("route"), "path", "unmatched"
            )  # template, low cardinality
            metrics.requests.labels(request.method, path, str(status)).inc()
            metrics.duration.labels(request.method, path).observe(time.perf_counter() - start)


def _add_business_routes(app: FastAPI, chaos: Chaos, registry: CollectorRegistry) -> None:
    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/metrics")
    async def metrics_endpoint() -> Response:
        return Response(generate_latest(registry), media_type=CONTENT_TYPE_LATEST)

    @app.get("/orders")
    async def orders() -> dict[str, list[dict[str, str | int]]]:
        if chaos.latency_ms:
            await asyncio.sleep(chaos.latency_ms / 1000)
        if chaos.error_rate and random.random() < chaos.error_rate:  # noqa: S311 - not crypto
            logger.error(
                "order lookup failed: database connection pool exhausted (timeout after 5s)"
            )
            raise HTTPException(status_code=500, detail="internal error")
        return {
            "orders": [{"id": 1, "item": "coffee", "qty": 2}, {"id": 2, "item": "bagel", "qty": 1}]
        }


def _add_chaos_routes(app: FastAPI, chaos: Chaos, metrics: Metrics) -> None:
    def changed(mode: str, active: bool) -> dict[str, float | int]:
        metrics.chaos.labels(mode).set(1 if active else 0)
        logger.warning("chaos %s %s state=%s", mode, "ON" if active else "OFF", chaos.snapshot())
        return chaos.snapshot()

    @app.get("/chaos")
    async def chaos_state() -> dict[str, float | int]:
        return chaos.snapshot()

    @app.post("/chaos/errors")
    async def errors_on(rate: Annotated[float, Query(gt=0, le=1)] = 0.5) -> dict[str, float | int]:
        chaos.error_rate = rate
        return changed("errors", True)

    @app.delete("/chaos/errors")
    async def errors_off() -> dict[str, float | int]:
        chaos.error_rate = 0.0
        return changed("errors", False)

    @app.post("/chaos/latency")
    async def latency_on(
        ms: Annotated[int, Query(gt=0, le=MAX_LATENCY_MS)] = 1500,
    ) -> dict[str, float | int]:
        chaos.latency_ms = ms
        return changed("latency", True)

    @app.delete("/chaos/latency")
    async def latency_off() -> dict[str, float | int]:
        chaos.latency_ms = 0
        return changed("latency", False)

    @app.post("/chaos/memory")
    async def memory_on(
        mb: Annotated[int, Query(gt=0, le=MAX_MEMORY_MB)] = min(32, MAX_MEMORY_MB),
    ) -> dict[str, float | int]:
        # Fill with non-zero bytes so the pages are really resident, not lazily zeroed.
        chaos.ballast = [bytearray(b"\x01" * MB) for _ in range(mb)]
        metrics.ballast.set(mb * MB)
        return changed("memory", True)

    @app.delete("/chaos/memory")
    async def memory_off() -> dict[str, float | int]:
        chaos.ballast = []
        metrics.ballast.set(0)
        return changed("memory", False)


def create_app() -> FastAPI:
    registry = CollectorRegistry()
    ProcessCollector(registry=registry)  # process_resident_memory_bytes etc. (Linux only)
    metrics = Metrics(registry)
    chaos = Chaos()
    app = FastAPI(title=SERVICE)
    app.state.chaos = chaos
    _add_metrics_middleware(app, metrics)
    _add_business_routes(app, chaos, registry)
    _add_chaos_routes(app, chaos, metrics)
    return app


app = create_app()
