"""FastAPI control plane: webhooks in, runs and approvals out, metrics for Prometheus.

The API is the *asynchronous* entry point (webhooks from GitHub and
Alertmanager). The synchronous one is the CLI inside a CI job. Both build the
same platform and produce the same ledger.
"""

from __future__ import annotations

import fnmatch
import functools
import hashlib
import hmac
import os
import threading
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel

from regent import __version__
from regent.core.models import RunRecord, RunStatus, Trigger
from regent.runtime.runner import Platform, Runner


class RunRequest(BaseModel):
    """Body of ``POST /runs``."""

    agent: str
    repository: str
    environment: str = "dev"
    event: str = "api"
    payload: dict[str, Any] = {}
    dry_run: bool = False
    approvals: list[str] = []


class ApproveRequest(BaseModel):
    """Body of ``POST /runs/{id}/approve``."""

    approver: str
    tools: list[str]
    """Tool globs approved for the re-run."""


class RunStore:
    """In-memory run index. Production swaps this for Postgres (see ADR-0009)."""

    def __init__(self) -> None:
        self._runs: dict[str, RunRecord] = {}
        self._lock = threading.Lock()

    def put(self, record: RunRecord) -> None:
        """Insert or replace."""
        with self._lock:
            self._runs[record.run_id] = record

    def get(self, run_id: str) -> RunRecord | None:
        """Fetch one run."""
        return self._runs.get(run_id)

    def list(self, limit: int = 100) -> list[RunRecord]:
        """Most recent runs first."""
        return sorted(self._runs.values(), key=lambda r: r.started_at, reverse=True)[:limit]


def _verify_github_signature(secret: str, body: bytes, signature: str | None) -> None:
    if not secret:
        raise HTTPException(503, "webhook secret not configured")
    if not signature or not signature.startswith("sha256="):
        raise HTTPException(401, "missing signature")
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(401, "bad signature")


#: GitHub event → (agent, payload extractor). Adding a workflow is adding a line.
def _github_route(event: str, payload: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    action = payload.get("action")
    if event == "pull_request" and action in ("opened", "synchronize", "ready_for_review"):
        pr = payload["pull_request"]
        author = pr["user"]["login"]
        if author.endswith("[bot]"):
            return "dependency-steward", {"number": pr["number"], "ci_green": False}
        return "pr-reviewer", {"number": pr["number"]}
    if (
        event == "workflow_run"
        and action == "completed"
        and payload["workflow_run"].get("conclusion") == "failure"
    ):
        run = payload["workflow_run"]
        prs = run.get("pull_requests") or []
        return "ci-triage", {"run_id": run["id"], "pr_number": prs[0]["number"] if prs else None}
    if event == "release" and action == "created":
        return "release-scribe", {
            "base": payload.get("previous_tag", "main"),
            "head": payload["release"]["tag_name"],
        }
    return None


def create_app(platform: Platform | None = None) -> FastAPI:
    """Application factory (``uvicorn regent.api.app:create_app --factory``)."""
    if platform is None:
        from regent.bootstrap import build_platform

        platform = build_platform()
    runner = Runner(platform)
    store = RunStore()
    app = FastAPI(title="Regent control plane", version=__version__)
    workspace = Path(os.environ.get("REGENT_WORKSPACE", "."))

    def _execute(req: RunRequest, trigger: Trigger) -> RunRecord:
        record = runner.run(
            req.agent,
            repository=req.repository,
            environment=req.environment,
            trigger=trigger,
            workspace=workspace,
            dry_run=req.dry_run,
            approvals=req.approvals,
        )
        store.put(record)
        return record

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @app.get("/readyz")
    def readyz() -> dict[str, Any]:
        return {
            "status": "ok",
            "agents": sorted(platform.agents),
            "mandates": len(platform.mandates.all()),
        }

    @app.get("/metrics")
    def metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @app.get("/agents")
    def agents() -> list[dict[str, str]]:
        return [
            {"name": a.name, "description": a.description, "highest_risk": a.highest_risk.name}
            for a in platform.agents.values()
        ]

    @app.post("/runs", status_code=202)
    def create_run(req: RunRequest, background: BackgroundTasks) -> dict[str, str]:
        if req.agent not in platform.agents:
            raise HTTPException(404, f"unknown agent {req.agent}")
        trigger = Trigger(source="api", event=req.event, actor="api", payload=req.payload)
        if req.dry_run:
            record = _execute(req, trigger)
            return {"run_id": record.run_id, "status": record.status.value}
        placeholder = RunRecord(
            agent=req.agent,
            repository=req.repository,
            environment=req.environment,
            trigger=trigger,
            mandate=platform.mandates.resolve(req.agent, req.repository, req.environment)
            or platform.mandates.all()[0],
        )
        store.put(placeholder)

        def _bg() -> None:
            record = _execute(req, trigger)
            record.run_id = placeholder.run_id
            store.put(record)

        background.add_task(_bg)
        return {"run_id": placeholder.run_id, "status": RunStatus.RUNNING.value}

    @app.get("/runs")
    def list_runs(limit: int = 50) -> list[dict[str, Any]]:
        return [
            {
                "run_id": r.run_id,
                "agent": r.agent,
                "repository": r.repository,
                "status": r.status.value,
                "started_at": r.started_at.isoformat(),
                "usd": r.usage.usd,
            }
            for r in store.list(limit)
        ]

    @app.get("/runs/{run_id}")
    def get_run(run_id: str) -> dict[str, Any]:
        record = store.get(run_id)
        if record is None:
            raise HTTPException(404, "unknown run")
        return record.model_dump(mode="json")

    @app.post("/runs/{run_id}/approve", status_code=202)
    def approve(run_id: str, req: ApproveRequest, background: BackgroundTasks) -> dict[str, str]:
        record = store.get(run_id)
        if record is None:
            raise HTTPException(404, "unknown run")
        if record.status is not RunStatus.AWAITING_APPROVAL or record.pending_call is None:
            raise HTTPException(409, f"run is {record.status.value}, nothing to approve")
        if not any(fnmatch.fnmatchcase(record.pending_call.tool, t) for t in req.tools):
            raise HTTPException(
                400, f"pending call is {record.pending_call.tool}, not in approved tools"
            )
        platform.ledger.append(
            run_id,
            "approval",
            {
                "approver": req.approver,
                "tools": req.tools,
                "call": record.pending_call.model_dump(),
            },
        )
        replay = RunRequest(
            agent=record.agent,
            repository=record.repository,
            environment=record.environment,
            event=record.trigger.event,
            payload=record.trigger.payload,
            approvals=req.tools,
        )
        trigger = Trigger(
            source="api",
            event=record.trigger.event,
            actor=req.approver,
            payload=record.trigger.payload,
        )

        def _bg() -> None:
            new = _execute(replay, trigger)
            store.put(new)

        background.add_task(_bg)
        return {"run_id": run_id, "status": "resumed"}

    @app.post("/webhooks/github", status_code=202)
    async def github_webhook(
        request: Request,
        background: BackgroundTasks,
        x_github_event: str = Header(default=""),
        x_hub_signature_256: str | None = Header(default=None),
    ) -> dict[str, Any]:
        body = await request.body()
        _verify_github_signature(
            os.environ.get("GITHUB_WEBHOOK_SECRET", ""), body, x_hub_signature_256
        )
        payload = await request.json()
        routed = _github_route(x_github_event, payload)
        if routed is None:
            return {"ignored": True, "event": x_github_event}
        agent, data = routed
        repository = payload.get("repository", {}).get("full_name", "")
        req = RunRequest(
            agent=agent,
            repository=repository,
            event=f"{x_github_event}.{payload.get('action')}",
            payload=data,
        )
        trigger = Trigger(
            source="github",
            event=req.event,
            actor=payload.get("sender", {}).get("login", "github"),
            payload=data,
        )
        background.add_task(functools.partial(_execute, req, trigger))
        return {"accepted": True, "agent": agent, "repository": repository}

    @app.post("/webhooks/alertmanager", status_code=202)
    async def alertmanager_webhook(
        request: Request,
        background: BackgroundTasks,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        token = os.environ.get("ALERTMANAGER_WEBHOOK_TOKEN", "")
        if not token or authorization != f"Bearer {token}":
            raise HTTPException(401, "bad token")
        payload = await request.json()
        accepted = 0
        for alert in payload.get("alerts", []):
            if alert.get("status") != "firing":
                continue
            labels = alert.get("labels", {})
            repository = labels.get("repository", os.environ.get("REGENT_DEFAULT_REPOSITORY", ""))
            data = {"alert": {**labels, **alert.get("annotations", {})}, "queries": []}
            req = RunRequest(
                agent="incident-triage",
                repository=repository,
                environment=labels.get("environment", "prod"),
                event="alert.firing",
                payload=data,
            )
            trigger = Trigger(
                source="alertmanager", event="alert.firing", actor="alertmanager", payload=data
            )
            background.add_task(functools.partial(_execute, req, trigger))
            accepted += 1
        return {"accepted": accepted}

    return app
