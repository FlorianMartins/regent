"""Read-only tools over the observability stack (Prometheus HTTP API)."""

from __future__ import annotations

import os
from typing import Any

import httpx

from regent.core.models import DataClass, RiskClass
from regent.tools.base import FunctionTool, ToolContext, ToolRegistry, ToolSpec


def register_observability_tools(registry: ToolRegistry, prometheus_url: str | None = None) -> None:
    """``metrics.query`` against Prometheus (instant queries only)."""
    base = (prometheus_url or os.environ.get("PROMETHEUS_URL", "http://prometheus:9090")).rstrip(
        "/"
    )

    def query(a: dict[str, Any], _ctx: ToolContext) -> Any:
        with httpx.Client(timeout=15.0) as client:
            resp = client.get(f"{base}/api/v1/query", params={"query": str(a["promql"])})
            resp.raise_for_status()
            data = resp.json()
        results = data.get("data", {}).get("result", [])[:50]
        return {"promql": a["promql"], "results": results, "count": len(results)}

    registry.register(
        FunctionTool(
            ToolSpec(
                name="metrics.query",
                description="Run an instant PromQL query",
                risk=RiskClass.READ,
                classification=DataClass.INTERNAL,
            ),
            query,
        )
    )
