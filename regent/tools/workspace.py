"""Workspace file tools: read and write inside the run's checkout, nowhere else."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from regent.core.models import DataClass, RiskClass
from regent.tools.base import FunctionTool, ToolContext, ToolRegistry, ToolSpec


def _inside(workspace: Path, relative: str) -> Path:
    target = (workspace / relative).resolve()
    root = workspace.resolve()
    if root != target and root not in target.parents:
        raise PermissionError(f"path escapes the workspace: {relative}")
    return target


def register_workspace_tools(registry: ToolRegistry) -> None:
    """``fs.read``, ``fs.write`` and ``fs.list``."""

    def read(a: dict[str, Any], ctx: ToolContext) -> Any:
        path = _inside(ctx.workspace, str(a["path"]))
        text = path.read_text(encoding="utf-8", errors="replace")
        limit = int(a.get("max_chars", 60_000))
        return {"path": str(a["path"]), "content": text[:limit], "truncated": len(text) > limit}

    def write(a: dict[str, Any], ctx: ToolContext) -> Any:
        path = _inside(ctx.workspace, str(a["path"]))
        content = str(a["content"])
        if ctx.dry_run:
            return {"dry_run": True, "path": str(a["path"]), "bytes": len(content.encode())}
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return {"path": str(a["path"]), "bytes": len(content.encode())}

    def listing(a: dict[str, Any], ctx: ToolContext) -> Any:
        base = _inside(ctx.workspace, str(a.get("path", ".")))
        pattern = str(a.get("glob", "**/*"))
        files = sorted(
            str(p.relative_to(ctx.workspace.resolve()))
            for p in base.glob(pattern)
            if p.is_file() and ".git" not in p.parts
        )
        return {"files": files[: int(a.get("limit", 500))], "total": len(files)}

    registry.register(
        FunctionTool(
            ToolSpec(
                name="fs.read",
                description="Read a file from the workspace",
                risk=RiskClass.READ,
                classification=DataClass.CONFIDENTIAL,
            ),
            read,
        )
    )
    registry.register(
        FunctionTool(
            ToolSpec(
                name="fs.write",
                description="Write a file in the workspace (a human still has to accept the PR)",
                risk=RiskClass.PROPOSE,
                classification=DataClass.INTERNAL,
            ),
            write,
        )
    )
    registry.register(
        FunctionTool(
            ToolSpec(
                name="fs.list",
                description="List files in the workspace",
                risk=RiskClass.READ,
                classification=DataClass.INTERNAL,
            ),
            listing,
        )
    )
