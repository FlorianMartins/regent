"""Run eval cases.

A case is a YAML file: a trigger, a fake world (tool answers), scripted model
answers (replay fixtures) and *assertions* on the run record. The suite runs
offline in CI on every change to a prompt, a skill, an agent or a mandate.
With ``--live`` the scripted model answers are ignored and the configured
provider is used; the deterministic assertions still apply, which is how
prompt regressions on a real model are caught nightly.
"""

from __future__ import annotations

import fnmatch
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel

from regent.bootstrap import DEFAULT_AGENTS
from regent.core.ledger import Ledger
from regent.core.models import RunRecord, Trigger
from regent.core.policy import MandateStore
from regent.gateway.gateway import Gateway
from regent.gateway.providers import ReplayProvider
from regent.runtime.runner import Platform, Runner
from regent.tools.base import FunctionTool, ToolContext, ToolRegistry, ToolSpec
from regent.tools.cloudguard_tool import register_cloudguard_tools
from regent.tools.github import GitHubClient, register_github_tools
from regent.tools.workspace import register_workspace_tools


def _stub_spec(name: str) -> ToolSpec:
    from regent.core.models import DataClass, RiskClass

    return ToolSpec(
        name=name, description="eval stub", risk=RiskClass.READ, classification=DataClass.INTERNAL
    )


def _constant(value: Any) -> Callable[[dict[str, Any], ToolContext], Any]:
    def _fn(_a: dict[str, Any], _c: ToolContext) -> Any:
        return value

    return _fn


class EvalResult(BaseModel):
    """Outcome of one case."""

    case: str
    agent: str
    passed: bool
    detail: str = ""
    usd: float = 0.0


class FakeGitHub(GitHubClient):
    """Answers GitHub requests from the case's ``world`` mapping."""

    def __init__(self, world: dict[str, Any]) -> None:
        super().__init__(use_env=False)  # nothing leaves the process
        self._world = world
        self.writes: list[dict[str, Any]] = []

    def request(  # noqa: D102
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        accept: str = "",
        params: dict[str, Any] | None = None,
    ) -> Any:
        del params  # instant queries only in evals
        self.calls.append((method, path))
        if method != "GET":
            self.writes.append({"method": method, "path": path, "json": json})
            return {
                "id": 1,
                "number": 1,
                "html_url": f"https://example.test{path}",
                "merged": True,
                "sha": "abc",
            }
        key = f"{accept.split('.')[-1] if 'diff' in accept or 'raw' in accept else 'json'} {path}"
        for pattern, value in self._world.items():
            if fnmatch.fnmatchcase(key, pattern) or fnmatch.fnmatchcase(path, pattern):
                return value
        raise KeyError(f"eval world has no answer for {key}")


def _build_tools(world: dict[str, Any]) -> tuple[ToolRegistry, FakeGitHub]:
    registry = ToolRegistry()
    github = FakeGitHub(world.get("github", {}))
    register_github_tools(registry, github)
    register_cloudguard_tools(registry)
    register_workspace_tools(registry)
    for name, value in world.get("tools", {}).items():
        registry.register(FunctionTool(_stub_spec(name), _constant(value)))
    return registry, github


def _assert(record: RunRecord, github: FakeGitHub, expectations: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    if "status" in expectations and record.status.value != expectations["status"]:
        failures.append(f"status {record.status.value} != {expectations['status']}")
    analysis = (record.output or {}).get("analysis", {})
    for path, expected in expectations.get("analysis", {}).items():
        actual = _dig(analysis, path)
        if not _matches(actual, expected):
            failures.append(f"analysis.{path} = {actual!r}, expected {expected!r}")
    for path, expected in expectations.get("actions", {}).items():
        actual = _dig((record.output or {}).get("actions", {}), path)
        if not _matches(actual, expected):
            failures.append(f"actions.{path} = {actual!r}, expected {expected!r}")
    writes = [f"{w['method']} {w['path']}" for w in github.writes]
    for expected_write in expectations.get("github_writes", []):
        if not any(fnmatch.fnmatchcase(w, expected_write) for w in writes):
            failures.append(f"expected GitHub write matching {expected_write!r}, got {writes}")
    for forbidden in expectations.get("github_writes_forbidden", []):
        if any(fnmatch.fnmatchcase(w, forbidden) for w in writes):
            failures.append(f"forbidden GitHub write happened: {forbidden!r}")
    if "max_usd" in expectations and record.usage.usd > float(expectations["max_usd"]):
        failures.append(f"spent ${record.usage.usd} > ${expectations['max_usd']}")
    if "error_matches" in expectations and not re.search(
        expectations["error_matches"], record.error or ""
    ):
        failures.append(f"error {record.error!r} does not match {expectations['error_matches']!r}")
    return failures


def _dig(data: Any, path: str) -> Any:
    current = data
    for part in path.split("."):
        if isinstance(current, list) and part.isdigit():
            current = current[int(part)] if int(part) < len(current) else None
        elif isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current


def _matches(actual: Any, expected: Any) -> bool:
    if isinstance(expected, dict) and "regex" in expected:
        return actual is not None and re.search(expected["regex"], str(actual)) is not None
    if isinstance(expected, dict) and "len" in expected:
        return isinstance(actual, list) and len(actual) == expected["len"]
    if isinstance(expected, dict) and "min_len" in expected:
        return isinstance(actual, list) and len(actual) >= expected["min_len"]
    if isinstance(expected, dict) and "in" in expected:
        return actual in expected["in"]
    return bool(actual == expected)


def run_case(path: Path, *, live: bool = False, mandates_dir: Path | None = None) -> EvalResult:
    """Run one YAML case."""
    case = yaml.safe_load(path.read_text(encoding="utf-8"))
    agent_name = str(case["agent"])
    if live:
        from regent.bootstrap import build_provider

        default, local, router = build_provider()
        gateway = Gateway(default, router=router, local_provider=local)
    else:
        replay = ReplayProvider(by_prompt=case.get("model", {}))
        gateway = Gateway(replay)
    tools, github = _build_tools(case.get("world", {}))
    store = MandateStore.from_directory(
        mandates_dir or Path(case.get("mandates_dir", "policies/mandates"))
    )
    platform = Platform(
        gateway=gateway,
        tools=tools,
        mandates=store,
        ledger=Ledger(None),
        agents=[cls() for cls in DEFAULT_AGENTS],
    )
    trigger = Trigger(
        source="eval", event=str(case.get("event", "eval")), payload=case.get("payload", {})
    )
    record = Runner(platform).run(
        agent_name,
        repository=str(case.get("repository", "acme/example")),
        environment=str(case.get("environment", "dev")),
        trigger=trigger,
        workspace=Path(case.get("workspace", ".")),
        dry_run=bool(case.get("dry_run", False)),
        approvals=case.get("approvals", ()),
    )
    failures = _assert(record, github, case.get("expect", {}))
    return EvalResult(
        case=path.stem,
        agent=agent_name,
        passed=not failures,
        detail="; ".join(failures) if failures else f"{record.status.value}",
        usd=record.usage.usd,
    )


def run_suite(directory: Path, *, live: bool = False) -> list[EvalResult]:
    """Run every ``*.yaml`` case under *directory* (recursively)."""
    return [run_case(p, live=live) for p in sorted(directory.rglob("*.y*ml"))]
