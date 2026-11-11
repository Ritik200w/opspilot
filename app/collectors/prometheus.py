"""Prometheus collector: error rate, request rate and latency for a service.

Uses the range-query API over the incident window. Metric and label names match
the demo-app / alert_rules.yml setup (``http_requests_total`` and
``http_request_duration_seconds`` labelled by ``service``).
"""

import logging
from dataclasses import dataclass
from typing import Any

import httpx

from app.collectors.base import CollectedContext, CollectionTarget
from app.models import ContextKind

logger = logging.getLogger(__name__)

# PromQL per metric. {service} is filled with the (escaped) service name.
_QUERIES: dict[str, str] = {
    "error_rate": (
        'sum(rate(http_requests_total{{service="{service}",status=~"5.."}}[1m]))'
        ' / sum(rate(http_requests_total{{service="{service}"}}[1m]))'
    ),
    "request_rate": 'sum(rate(http_requests_total{{service="{service}"}}[1m]))',
    "latency_p95_seconds": (
        "histogram_quantile(0.95, sum(rate("
        'http_request_duration_seconds_bucket{{service="{service}"}}[1m]'
        ")) by (le))"
    ),
}


def _escape(label_value: str) -> str:
    return label_value.replace("\\", "\\\\").replace('"', '\\"')


@dataclass
class PrometheusCollector:
    """Collects service metrics from a Prometheus server."""

    client: httpx.AsyncClient
    base_url: str
    step_seconds: int = 15
    max_points: int = 500
    timeout_seconds: float = 10.0
    kind: ContextKind = ContextKind.METRICS
    name: str = "prometheus"

    async def collect(self, target: CollectionTarget) -> CollectedContext:
        service = _escape(target.service)
        metrics: dict[str, Any] = {}
        truncated = False
        for key, template in _QUERIES.items():
            promql = template.format(service=service)
            series, series_truncated = await self._range_query(promql, target)
            metrics[key] = {"query": promql, "series": series}
            truncated = truncated or series_truncated
        return CollectedContext(
            kind=self.kind,
            query="\n".join(entry["query"] for entry in metrics.values()),
            window=target.window,
            data={"service": target.service, "metrics": metrics},
            truncated=truncated,
        )

    async def _range_query(
        self, promql: str, target: CollectionTarget
    ) -> tuple[list[dict[str, Any]], bool]:
        response = await self.client.get(
            f"{self.base_url.rstrip('/')}/api/v1/query_range",
            params={
                "query": promql,
                "start": target.window.start.timestamp(),
                "end": target.window.end.timestamp(),
                "step": f"{self.step_seconds}s",
            },
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("status") != "success":
            raise RuntimeError(f"prometheus query failed: {payload.get('error', 'unknown error')}")
        return self._parse_result(payload.get("data", {}).get("result", []))

    def _parse_result(self, result: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], bool]:
        series: list[dict[str, Any]] = []
        truncated = False
        for entry in result:
            values = entry.get("values", [])
            if len(values) > self.max_points:
                values = values[-self.max_points :]  # keep the most recent points
                truncated = True
            series.append(
                {
                    "labels": entry.get("metric", {}),
                    "values": [[ts, val] for ts, val in values],
                }
            )
        return series, truncated
