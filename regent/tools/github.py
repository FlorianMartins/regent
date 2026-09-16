"""GitHub tools, backed by the REST API through ``httpx``.

Design choices:

* One thin client, no SDK: the platform needs a dozen endpoints and must stay
  auditable. Every call is logged with its method and path.
* The token comes from the environment (``GITHUB_TOKEN`` — the job token in
  Actions, a GitHub App installation token elsewhere). Never from arguments,
  never from an LLM.
* Write tools honour ``dry_run``: they return the payload they *would* send.
* Risk classes are declared once, here, next to the endpoint.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from regent.core.models import DataClass, RiskClass
from regent.tools.base import FunctionTool, ToolContext, ToolRegistry, ToolSpec

API = "https://api.github.com"


class GitHubClient:
    """Minimal REST client. Instantiate once per run."""

    def __init__(
        self,
        token: str | None = None,
        base_url: str = API,
        timeout_s: float = 30.0,
        *,
        use_env: bool = True,
    ):
        env_token = os.environ.get("GITHUB_TOKEN", "") if use_env else ""
        self._token = token if token is not None else env_token
        self._base = base_url.rstrip("/")
        self._timeout = timeout_s
        self.calls: list[tuple[str, str]] = []

    def _headers(self, accept: str = "application/vnd.github+json") -> dict[str, str]:
        headers = {"accept": accept, "x-github-api-version": "2022-11-28"}
        if self._token:
            headers["authorization"] = f"Bearer {self._token}"
        return headers

    def request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        accept: str = "application/vnd.github+json",
        params: dict[str, Any] | None = None,
    ) -> Any:
        """Issue one request and return the decoded body (text for diffs and logs)."""
        self.calls.append((method, path))
        with httpx.Client(timeout=self._timeout, follow_redirects=True) as client:
            resp = client.request(
                method,
                f"{self._base}{path}",
                json=json,
                params=params,
                headers=self._headers(accept),
            )
            resp.raise_for_status()
            if "json" in resp.headers.get("content-type", "") and resp.content:
                return resp.json()
            return resp.text


def _repo_path(ctx: ToolContext) -> str:
    owner, _, name = ctx.repository.partition("/")
    if not owner or not name:
        raise ValueError(f"repository must be 'owner/name', got '{ctx.repository}'")
    return f"/repos/{owner}/{name}"


def register_github_tools(registry: ToolRegistry, client: GitHubClient) -> None:
    """Register every GitHub tool against *client*."""

    def get_pr(a: dict[str, Any], ctx: ToolContext) -> Any:
        pr = client.request("GET", f"{_repo_path(ctx)}/pulls/{int(a['number'])}")
        return {
            "number": pr["number"],
            "title": pr["title"],
            "body": pr.get("body") or "",
            "author": pr["user"]["login"],
            "base": pr["base"]["ref"],
            "head": pr["head"]["ref"],
            "head_sha": pr["head"]["sha"],
            "changed_files": pr.get("changed_files", 0),
            "additions": pr.get("additions", 0),
            "deletions": pr.get("deletions", 0),
            "labels": [label["name"] for label in pr.get("labels", [])],
        }

    def get_pr_diff(a: dict[str, Any], ctx: ToolContext) -> Any:
        diff = client.request(
            "GET",
            f"{_repo_path(ctx)}/pulls/{int(a['number'])}",
            accept="application/vnd.github.diff",
        )
        limit = int(a.get("max_chars", 120_000))
        text = str(diff)
        return {"diff": text[:limit], "truncated": len(text) > limit, "chars": len(text)}

    def list_pr_files(a: dict[str, Any], ctx: ToolContext) -> Any:
        files = client.request(
            "GET", f"{_repo_path(ctx)}/pulls/{int(a['number'])}/files", params={"per_page": 100}
        )
        return [
            {"filename": f["filename"], "status": f["status"], "changes": f.get("changes", 0)}
            for f in files
        ]

    def comment(a: dict[str, Any], ctx: ToolContext) -> Any:
        payload = {"body": str(a["body"])}
        path = f"{_repo_path(ctx)}/issues/{int(a['number'])}/comments"
        if ctx.dry_run:
            return {"dry_run": True, "method": "POST", "path": path, "payload": payload}
        created = client.request("POST", path, json=payload)
        return {"id": created["id"], "url": created.get("html_url")}

    def create_review(a: dict[str, Any], ctx: ToolContext) -> Any:
        comments = [
            {"path": c["path"], "line": int(c["line"]), "side": "RIGHT", "body": c["body"]}
            for c in a.get("comments", [])
        ]
        payload = {"body": str(a["body"]), "event": "COMMENT", "comments": comments}
        path = f"{_repo_path(ctx)}/pulls/{int(a['number'])}/reviews"
        if ctx.dry_run:
            return {"dry_run": True, "method": "POST", "path": path, "payload": payload}
        created = client.request("POST", path, json=payload)
        return {"id": created["id"], "url": created.get("html_url")}

    def add_labels(a: dict[str, Any], ctx: ToolContext) -> Any:
        payload = {"labels": [str(label) for label in a["labels"]]}
        path = f"{_repo_path(ctx)}/issues/{int(a['number'])}/labels"
        if ctx.dry_run:
            return {"dry_run": True, "method": "POST", "path": path, "payload": payload}
        client.request("POST", path, json=payload)
        return {"labels": payload["labels"]}

    def create_issue(a: dict[str, Any], ctx: ToolContext) -> Any:
        payload = {
            "title": str(a["title"]),
            "body": str(a.get("body", "")),
            "labels": list(a.get("labels", [])),
        }
        path = f"{_repo_path(ctx)}/issues"
        if ctx.dry_run:
            return {"dry_run": True, "method": "POST", "path": path, "payload": payload}
        created = client.request("POST", path, json=payload)
        return {"number": created["number"], "url": created.get("html_url")}

    def get_workflow_run(a: dict[str, Any], ctx: ToolContext) -> Any:
        run = client.request("GET", f"{_repo_path(ctx)}/actions/runs/{int(a['run_id'])}")
        jobs = client.request("GET", f"{_repo_path(ctx)}/actions/runs/{int(a['run_id'])}/jobs")
        return {
            "id": run["id"],
            "name": run.get("name"),
            "status": run.get("status"),
            "conclusion": run.get("conclusion"),
            "head_sha": run.get("head_sha"),
            "head_branch": run.get("head_branch"),
            "run_attempt": run.get("run_attempt", 1),
            "event": run.get("event"),
            "jobs": [
                {
                    "id": j["id"],
                    "name": j["name"],
                    "conclusion": j.get("conclusion"),
                    "failed_steps": [
                        s["name"] for s in j.get("steps", []) if s.get("conclusion") == "failure"
                    ],
                }
                for j in jobs.get("jobs", [])
            ],
        }

    def get_job_logs(a: dict[str, Any], ctx: ToolContext) -> Any:
        logs = client.request(
            "GET", f"{_repo_path(ctx)}/actions/jobs/{int(a['job_id'])}/logs", accept="text/plain"
        )
        text = str(logs)
        limit = int(a.get("max_chars", 60_000))
        # Keep the *end* of the log: that is where the failure is.
        return {"logs": text[-limit:], "truncated": len(text) > limit, "chars": len(text)}

    def rerun_failed_jobs(a: dict[str, Any], ctx: ToolContext) -> Any:
        path = f"{_repo_path(ctx)}/actions/runs/{int(a['run_id'])}/rerun-failed-jobs"
        if ctx.dry_run:
            return {"dry_run": True, "method": "POST", "path": path}
        client.request("POST", path)
        return {"rerun": True, "run_id": int(a["run_id"])}

    def create_pull_request(a: dict[str, Any], ctx: ToolContext) -> Any:
        payload = {
            "title": str(a["title"]),
            "body": str(a.get("body", "")),
            "head": str(a["head"]),
            "base": str(a["base"]),
            "draft": bool(a.get("draft", True)),
        }
        path = f"{_repo_path(ctx)}/pulls"
        if ctx.dry_run:
            return {"dry_run": True, "method": "POST", "path": path, "payload": payload}
        created = client.request("POST", path, json=payload)
        return {"number": created["number"], "url": created.get("html_url")}

    def merge_pull_request(a: dict[str, Any], ctx: ToolContext) -> Any:
        payload = {"merge_method": str(a.get("method", "squash"))}
        path = f"{_repo_path(ctx)}/pulls/{int(a['number'])}/merge"
        if ctx.dry_run:
            return {"dry_run": True, "method": "PUT", "path": path, "payload": payload}
        merged = client.request("PUT", path, json=payload)
        return {"merged": bool(merged.get("merged")), "sha": merged.get("sha")}

    def list_commits(a: dict[str, Any], ctx: ToolContext) -> Any:
        params = {"sha": str(a.get("ref", "main")), "per_page": int(a.get("limit", 50))}
        commits = client.request("GET", f"{_repo_path(ctx)}/commits", params=params)
        return [
            {
                "sha": c["sha"][:12],
                "message": c["commit"]["message"].split("\n", 1)[0],
                "author": (c["commit"].get("author") or {}).get("name", ""),
            }
            for c in commits
        ]

    def compare(a: dict[str, Any], ctx: ToolContext) -> Any:
        data = client.request("GET", f"{_repo_path(ctx)}/compare/{a['base']}...{a['head']}")
        return {
            "ahead_by": data.get("ahead_by", 0),
            "commits": [
                {"sha": c["sha"][:12], "message": c["commit"]["message"]}
                for c in data.get("commits", [])
            ],
        }

    def create_release(a: dict[str, Any], ctx: ToolContext) -> Any:
        payload = {
            "tag_name": str(a["tag"]),
            "name": str(a.get("name", a["tag"])),
            "body": str(a.get("body", "")),
            "draft": bool(a.get("draft", True)),
        }
        path = f"{_repo_path(ctx)}/releases"
        if ctx.dry_run:
            return {"dry_run": True, "method": "POST", "path": path, "payload": payload}
        created = client.request("POST", path, json=payload)
        return {"id": created["id"], "url": created.get("html_url")}

    def get_file(a: dict[str, Any], ctx: ToolContext) -> Any:
        params = {"ref": str(a.get("ref", "main"))}
        data = client.request(
            "GET",
            f"{_repo_path(ctx)}/contents/{a['path']}",
            params=params,
            accept="application/vnd.github.raw+json",
        )
        return {"path": a["path"], "content": str(data)[: int(a.get("max_chars", 60_000))]}

    table: list[tuple[str, str, RiskClass, Any, DataClass]] = [
        (
            "github.get_pr",
            "Metadata of a pull request",
            RiskClass.READ,
            get_pr,
            DataClass.INTERNAL,
        ),
        (
            "github.get_pr_diff",
            "Unified diff of a pull request (truncated)",
            RiskClass.READ,
            get_pr_diff,
            DataClass.CONFIDENTIAL,
        ),
        (
            "github.list_pr_files",
            "Files touched by a pull request",
            RiskClass.READ,
            list_pr_files,
            DataClass.INTERNAL,
        ),
        (
            "github.get_file",
            "Content of one file at a ref",
            RiskClass.READ,
            get_file,
            DataClass.CONFIDENTIAL,
        ),
        (
            "github.comment",
            "Post a comment on an issue or pull request",
            RiskClass.ADVISE,
            comment,
            DataClass.INTERNAL,
        ),
        (
            "github.create_review",
            "Post a review with inline comments (never approves)",
            RiskClass.ADVISE,
            create_review,
            DataClass.INTERNAL,
        ),
        (
            "github.add_labels",
            "Add labels to an issue or pull request",
            RiskClass.ADVISE,
            add_labels,
            DataClass.INTERNAL,
        ),
        (
            "github.create_issue",
            "Open an issue",
            RiskClass.ADVISE,
            create_issue,
            DataClass.INTERNAL,
        ),
        (
            "github.get_workflow_run",
            "Status and jobs of a workflow run",
            RiskClass.READ,
            get_workflow_run,
            DataClass.INTERNAL,
        ),
        (
            "github.get_job_logs",
            "Tail of a job's logs",
            RiskClass.READ,
            get_job_logs,
            DataClass.CONFIDENTIAL,
        ),
        (
            "github.rerun_failed_jobs",
            "Re-run the failed jobs of a workflow run",
            RiskClass.ACT_REVERSIBLE,
            rerun_failed_jobs,
            DataClass.INTERNAL,
        ),
        (
            "github.create_pull_request",
            "Open a (draft) pull request from an existing branch",
            RiskClass.PROPOSE,
            create_pull_request,
            DataClass.INTERNAL,
        ),
        (
            "github.merge_pull_request",
            "Merge a pull request (revertable)",
            RiskClass.ACT_REVERSIBLE,
            merge_pull_request,
            DataClass.INTERNAL,
        ),
        (
            "github.list_commits",
            "Recent commits on a ref",
            RiskClass.READ,
            list_commits,
            DataClass.INTERNAL,
        ),
        (
            "github.compare",
            "Commits between two refs",
            RiskClass.READ,
            compare,
            DataClass.INTERNAL,
        ),
        (
            "github.create_release",
            "Create a (draft) release",
            RiskClass.PROPOSE,
            create_release,
            DataClass.INTERNAL,
        ),
    ]
    for name, description, risk, fn, classification in table:
        registry.register(
            FunctionTool(
                ToolSpec(
                    name=name, description=description, risk=risk, classification=classification
                ),
                fn,
            )
        )
