from pathlib import Path

import pytest

from regent.core.models import RiskClass
from regent.tools.base import ToolContext, ToolRegistry
from regent.tools.cloudguard_tool import scan
from regent.tools.github import GitHubClient, register_github_tools
from regent.tools.sandbox import run_command
from regent.tools.workspace import register_workspace_tools


def ctx(tmp_path: Path, **kw) -> ToolContext:
    return ToolContext(run_id="r", repository="acme/x", workspace=tmp_path, **kw)


def test_sandbox_runs_allow_listed_command(tmp_path: Path):
    out = run_command("git.status", [], tmp_path)
    assert out["exit_code"] in (0, 128) and "argv" in out


def test_sandbox_refuses_unknown_and_metacharacters(tmp_path: Path):
    with pytest.raises(PermissionError):
        run_command("rm", ["-rf", "/"], tmp_path)
    with pytest.raises(ValueError, match="metacharacters"):
        run_command("git.log", ["; rm -rf /"], tmp_path)
    with pytest.raises(ValueError, match="flags"):
        run_command("git.log", ["--exec=evil"], tmp_path)


def test_sandbox_missing_binary(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))
    out = run_command("terraform.validate", [], tmp_path)
    assert out["exit_code"] == 127


def test_sandbox_tools_declare_risk(tmp_path: Path):
    from regent.tools.sandbox import register_sandbox_tools

    reg = ToolRegistry()
    register_sandbox_tools(reg)
    assert reg.get("exec.kubectl.rollout.undo").spec.risk is RiskClass.ACT_REVERSIBLE
    assert reg.get("exec.git.status").spec.risk is RiskClass.READ
    dry = reg.get("exec.kubectl.rollout.undo").run(
        {"args": ["deploy/x"]}, ctx(tmp_path, dry_run=True)
    )
    assert dry.output["dry_run"] is True


def test_workspace_tools_are_jailed(tmp_path: Path):
    reg = ToolRegistry()
    register_workspace_tools(reg)
    (tmp_path / "a.txt").write_text("hello")
    assert reg.get("fs.read").run({"path": "a.txt"}, ctx(tmp_path)).output["content"] == "hello"
    escaped = reg.get("fs.read").run({"path": "../../etc/passwd"}, ctx(tmp_path))
    assert not escaped.ok and "escapes" in escaped.error
    written = reg.get("fs.write").run({"path": "sub/b.txt", "content": "x"}, ctx(tmp_path))
    assert written.ok and (tmp_path / "sub" / "b.txt").exists()
    listing = reg.get("fs.list").run({}, ctx(tmp_path))
    assert set(listing.output["files"]) == {"a.txt", "sub/b.txt"}


def test_registry_rejects_duplicates():
    reg = ToolRegistry()
    register_workspace_tools(reg)
    with pytest.raises(ValueError, match="already registered"):
        register_workspace_tools(reg)
    with pytest.raises(KeyError):
        reg.get("nope")
    assert "fs.read" in reg and len(reg.specs()) == 3


def test_cloudguard_scan(tmp_path: Path):
    (tmp_path / "Dockerfile").write_text("FROM ubuntu:latest\nENV DB_PASSWORD=hunter2hunter2\n")
    out = scan(["Dockerfile"], tmp_path)
    ids = {f["rule_id"] for f in out["findings"]}
    assert "CG_DOCKER_005" in ids and out["total"] >= 2 and out["counts"]


def test_github_client_headers_and_repo_validation(monkeypatch, tmp_path: Path):
    import httpx

    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("authorization")
        seen["path"] = request.url.path
        if request.headers["accept"].endswith("diff"):
            return httpx.Response(
                200, text="diff --git a b", headers={"content-type": "text/plain"}
            )
        return httpx.Response(
            200,
            json={
                "number": 1,
                "title": "t",
                "body": None,
                "user": {"login": "u"},
                "base": {"ref": "main"},
                "head": {"ref": "h", "sha": "s"},
            },
        )

    real = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(handler), **kw)
    )
    client = GitHubClient(token="tok")
    reg = ToolRegistry()
    register_github_tools(reg, client)
    out = reg.get("github.get_pr").run({"number": 1}, ctx(tmp_path))
    assert out.ok and seen["auth"] == "Bearer tok" and seen["path"] == "/repos/acme/x/pulls/1"
    diff = reg.get("github.get_pr_diff").run({"number": 1, "max_chars": 5}, ctx(tmp_path))
    assert diff.output["truncated"] is True
    bad = reg.get("github.get_pr").run(
        {"number": 1}, ToolContext(run_id="r", repository="nope", workspace=tmp_path)
    )
    assert not bad.ok and "owner/name" in bad.error


def test_github_write_tools_honour_dry_run(tmp_path: Path):
    reg = ToolRegistry()
    register_github_tools(reg, GitHubClient(token="t"))
    for name, args in [
        ("github.comment", {"number": 1, "body": "x"}),
        ("github.create_pull_request", {"title": "t", "head": "h", "base": "b"}),
        ("github.merge_pull_request", {"number": 1}),
        ("github.rerun_failed_jobs", {"run_id": 1}),
        ("github.create_release", {"tag": "v1"}),
        ("github.create_issue", {"title": "t"}),
        ("github.add_labels", {"number": 1, "labels": ["a"]}),
        ("github.create_review", {"number": 1, "body": "b", "comments": []}),
    ]:
        out = reg.get(name).run(args, ctx(tmp_path, dry_run=True))
        assert out.ok and out.output["dry_run"] is True, name
