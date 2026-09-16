"""Prometheus metrics for the platform. Labels are low-cardinality on purpose."""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

RUNS_TOTAL = Counter("regent_runs_total", "Agent runs by outcome", ["agent", "status"])
LLM_CALLS_TOTAL = Counter("regent_llm_calls_total", "LLM calls", ["agent", "provider", "model"])
LLM_TOKENS_TOTAL = Counter(
    "regent_llm_tokens_total", "Tokens consumed", ["agent", "model", "direction"]
)
LLM_USD_TOTAL = Counter("regent_llm_usd_total", "Estimated spend in USD", ["agent", "model"])
TOOL_CALLS_TOTAL = Counter(
    "regent_tool_calls_total", "Tool calls by decision", ["agent", "tool", "decision"]
)
RUN_DURATION = Histogram(
    "regent_run_duration_seconds",
    "Wall-clock time of a run",
    ["agent"],
    buckets=(1, 5, 15, 30, 60, 120, 300, 600, 900),
)
VERIFICATIONS_TOTAL = Counter(
    "regent_verifications_total", "Verifier verdicts", ["agent", "verdict"]
)
REDACTIONS_TOTAL = Counter(
    "regent_redactions_total", "Secrets redacted before an LLM call", ["kind"]
)
RUNS_IN_FLIGHT = Gauge("regent_runs_in_flight", "Runs currently executing", ["agent"])
