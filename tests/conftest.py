"""Shared fixtures: an offline platform with scripted model answers and a fake GitHub."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from regent.bootstrap import DEFAULT_AGENTS
from regent.core.ledger import Ledger
from regent.core.models import Trigger
from regent.core.policy import MandateStore
from regent.evals.runner import FakeGitHub
from regent.gateway.gateway import Gateway
from regent.gateway.providers import ReplayProvider
from regent.runtime.runner import Platform, Runner
from regent.tools.base import ToolRegistry
from regent.tools.cloudguard_tool import register_cloudguard_tools
from regent.tools.github import register_github_tools
from regent.tools.sandbox import register_sandbox_tools
from regent.tools.workspace import register_workspace_tools

ROOT = Path(__file__).resolve().parent.parent
MANDATES = ROOT / "policies" / "mandates"

ACCEPT = {"json": {"accept": True, "issues": [], "confidence": 0.9}}
REJECT = {"json": {"accept": False, "issues": ["claim without evidence"], "confidence": 0.8}}

SAMPLE_DIFF = """diff --git a/app/db.py b/app/db.py
--- a/app/db.py
+++ b/app/db.py
@@ -1,4 +1,6 @@
 import sqlite3
-def find(user):
-    return db.execute("SELECT * FROM users WHERE name = ?", (user,))
+def find(user):
+    query = "SELECT * FROM users WHERE name = '" + user + "'"
+    return db.execute(query)
"""

SAMPLE_PR = {
    "number": 42,
    "title": "feat(db): faster user lookup",
    "body": "Speeds up lookups.",
    "user": {"login": "alice"},
    "base": {"ref": "main"},
    "head": {"ref": "feat/lookup", "sha": "deadbeef"},
    "changed_files": 1,
    "additions": 3,
    "deletions": 2,
    "labels": [],
}


def github_world(**extra: Any) -> dict[str, Any]:
    world: dict[str, Any] = {
        "json /repos/*/pulls/42": SAMPLE_PR,
        "diff /repos/*/pulls/42": SAMPLE_DIFF,
        "json /repos/*/pulls/42/files": [
            {"filename": "app/db.py", "status": "modified", "changes": 5}
        ],
    }
    world.update(extra)
    return world


@pytest.fixture
def mandates() -> MandateStore:
    return MandateStore.from_directory(MANDATES)


@pytest.fixture
def make_platform(
    tmp_path: Path, mandates: MandateStore
) -> Callable[..., tuple[Platform, ReplayProvider, FakeGitHub]]:
    def _make(
        model: dict[str, list[dict[str, Any]]] | None = None,
        world: dict[str, Any] | None = None,
        ledger_path: Path | None = None,
        store: MandateStore | None = None,
    ) -> tuple[Platform, ReplayProvider, FakeGitHub]:
        replay = ReplayProvider(by_prompt=model or {})
        github = FakeGitHub(world if world is not None else github_world())
        tools = ToolRegistry()
        register_github_tools(tools, github)
        register_cloudguard_tools(tools)
        register_workspace_tools(tools)
        register_sandbox_tools(tools)
        platform = Platform(
            gateway=Gateway(replay),
            tools=tools,
            mandates=store or mandates,
            ledger=Ledger(ledger_path if ledger_path else tmp_path / "ledger.jsonl"),
            agents=[cls() for cls in DEFAULT_AGENTS],
        )
        return platform, replay, github

    return _make


@pytest.fixture
def trigger() -> Callable[..., Trigger]:
    def _t(event: str = "test", **payload: Any) -> Trigger:
        return Trigger(source="test", event=event, actor="pytest", payload=payload)

    return _t


@pytest.fixture
def runner(
    make_platform: Callable[..., tuple[Platform, ReplayProvider, FakeGitHub]],
) -> Callable[..., Any]:
    """Return ``run(agent, model=..., world=..., **payload) -> (record, github, replay)``."""

    def _run(
        agent: str,
        *,
        model: dict[str, Any],
        world: dict[str, Any] | None = None,
        repository: str = "acme/example",
        environment: str = "dev",
        dry_run: bool = False,
        approvals: tuple[str, ...] = (),
        workspace: Path | None = None,
        store: MandateStore | None = None,
        **payload: Any,
    ) -> tuple[Any, FakeGitHub, ReplayProvider]:
        platform, replay, github = make_platform(model=model, world=world, store=store)
        record = Runner(platform).run(
            agent,
            repository=repository,
            environment=environment,
            trigger=Trigger(source="test", event="test", actor="pytest", payload=payload),
            workspace=workspace,
            dry_run=dry_run,
            approvals=approvals,
        )
        return record, github, replay

    return _run
