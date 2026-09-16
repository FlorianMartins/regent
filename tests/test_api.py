import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient

from regent.api.app import _github_route, create_app
from tests.conftest import ACCEPT
from tests.test_runtime import REVIEW


@pytest.fixture
def client(make_platform, monkeypatch):
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "s3cret")
    monkeypatch.setenv("ALERTMANAGER_WEBHOOK_TOKEN", "tok")
    platform, _replay, github = make_platform(
        model={"pr_reviewer@1": [REVIEW], "verifier@1": [ACCEPT]}
    )
    app = create_app(platform)
    return TestClient(app), github


def test_health_and_catalogue(client):
    c, _ = client
    assert c.get("/healthz").json()["status"] == "ok"
    assert "pr-reviewer" in c.get("/readyz").json()["agents"]
    assert any(a["name"] == "iac-guardian" for a in c.get("/agents").json())
    assert b"regent_runs_total" in c.get("/metrics").content or c.get("/metrics").status_code == 200


def test_dry_run_is_synchronous(client):
    c, github = client
    r = c.post(
        "/runs",
        json={
            "agent": "pr-reviewer",
            "repository": "acme/example",
            "payload": {"number": 42},
            "dry_run": True,
        },
    )
    assert r.status_code == 202 and r.json()["status"] == "succeeded"
    run = c.get(f"/runs/{r.json()['run_id']}").json()
    assert run["output"]["actions"]["review"]["dry_run"] is True and github.writes == []
    assert c.get("/runs").json()[0]["agent"] == "pr-reviewer"
    assert c.get("/runs/nope").status_code == 404
    assert c.post("/runs", json={"agent": "nope", "repository": "a/b"}).status_code == 404


def test_background_run_and_approval_flow(make_platform, monkeypatch):
    from regent.core.models import Autonomy, Mandate
    from regent.core.policy import MandateStore

    store = MandateStore(
        [
            Mandate(
                agent="pr-reviewer",
                autonomy=Autonomy.L1_ADVISE,
                allowed_tools=("github.*",),
                requires_approval=("github.create_review",),
            )
        ]
    )
    platform, _, github = make_platform(
        model={"pr_reviewer@1": [REVIEW, REVIEW], "verifier@1": [ACCEPT, ACCEPT]}, store=store
    )
    c = TestClient(create_app(platform))
    r = c.post(
        "/runs",
        json={"agent": "pr-reviewer", "repository": "acme/example", "payload": {"number": 42}},
    )
    run_id = r.json()["run_id"]
    run = c.get(f"/runs/{run_id}").json()
    assert (
        run["status"] == "awaiting_approval"
        and run["pending_call"]["tool"] == "github.create_review"
    )
    bad = c.post(
        f"/runs/{run_id}/approve",
        json={"approver": "alice", "tools": ["github.merge_pull_request"]},
    )
    assert bad.status_code == 400
    ok = c.post(
        f"/runs/{run_id}/approve", json={"approver": "alice", "tools": ["github.create_review"]}
    )
    assert ok.status_code == 202
    assert any(w["path"].endswith("/reviews") for w in github.writes)
    assert any(
        e.kind == "approval" and e.data["approver"] == "alice" for e in platform.ledger.events()
    )
    assert c.post(
        f"/runs/{run_id}/approve", json={"approver": "a", "tools": ["x"]}
    ).status_code in (400, 409)
    assert c.post("/runs/nope/approve", json={"approver": "a", "tools": ["x"]}).status_code == 404


def test_github_webhook_signature_and_routing(client):
    c, github = client
    body = json.dumps(
        {
            "action": "opened",
            "pull_request": {"number": 42, "user": {"login": "alice"}},
            "repository": {"full_name": "acme/example"},
            "sender": {"login": "alice"},
        }
    ).encode()
    assert (
        c.post(
            "/webhooks/github", content=body, headers={"x-github-event": "pull_request"}
        ).status_code
        == 401
    )
    sig = "sha256=" + hmac.new(b"s3cret", body, hashlib.sha256).hexdigest()
    r = c.post(
        "/webhooks/github",
        content=body,
        headers={
            "x-github-event": "pull_request",
            "x-hub-signature-256": sig,
            "content-type": "application/json",
        },
    )
    assert r.status_code == 202 and r.json()["agent"] == "pr-reviewer"
    assert any(w["path"].endswith("/reviews") for w in github.writes)
    other = json.dumps({"action": "labeled"}).encode()
    sig2 = "sha256=" + hmac.new(b"s3cret", other, hashlib.sha256).hexdigest()
    assert (
        c.post(
            "/webhooks/github",
            content=other,
            headers={
                "x-github-event": "issues",
                "x-hub-signature-256": sig2,
                "content-type": "application/json",
            },
        ).json()["ignored"]
        is True
    )


def test_github_route_table():
    assert (
        _github_route(
            "pull_request",
            {
                "action": "opened",
                "pull_request": {"number": 1, "user": {"login": "dependabot[bot]"}},
            },
        )[0]
        == "dependency-steward"
    )
    assert _github_route(
        "workflow_run",
        {
            "action": "completed",
            "workflow_run": {"id": 5, "conclusion": "failure", "pull_requests": []},
        },
    ) == ("ci-triage", {"run_id": 5, "pr_number": None})
    assert (
        _github_route(
            "workflow_run",
            {"action": "completed", "workflow_run": {"id": 5, "conclusion": "success"}},
        )
        is None
    )
    assert (
        _github_route("release", {"action": "created", "release": {"tag_name": "v2"}})[1]["head"]
        == "v2"
    )


def test_alertmanager_webhook(client):
    c, _github = client
    payload = {
        "alerts": [
            {
                "status": "firing",
                "labels": {
                    "alertname": "HighErrorRate",
                    "repository": "acme/example",
                    "environment": "prod",
                },
                "annotations": {"summary": "errors"},
            },
            {"status": "resolved", "labels": {}},
        ]
    }
    assert c.post("/webhooks/alertmanager", json=payload).status_code == 401
    r = c.post("/webhooks/alertmanager", json=payload, headers={"authorization": "Bearer tok"})
    assert r.status_code == 202 and r.json()["accepted"] == 1
