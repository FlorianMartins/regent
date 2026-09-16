"""Command execution with guard rails.

Agents never get a shell. They get *named commands* from an allow-list, run
with a timeout, a scrubbed environment and a working directory pinned to the
run's workspace. Anything else is a policy violation, not a feature request.

In production the same interface is backed by an ephemeral job pod (gVisor or
Kata) with no network; this in-process version is for CI runners and local use.
"""

from __future__ import annotations

import os
import shlex
import subprocess  # nosec B404
from pathlib import Path
from typing import Any

from regent.core.models import DataClass, RiskClass
from regent.tools.base import FunctionTool, ToolContext, ToolRegistry, ToolSpec

#: Name → (argv prefix, risk). Arguments supplied by the agent are appended
#: after validation and are never interpreted by a shell.
ALLOWED_COMMANDS: dict[str, tuple[tuple[str, ...], RiskClass]] = {
    "git.status": (("git", "status", "--porcelain"), RiskClass.READ),
    "git.diff": (("git", "diff", "--stat"), RiskClass.READ),
    "git.log": (("git", "log", "--oneline", "-n", "30"), RiskClass.READ),
    "pytest": (("python", "-m", "pytest", "-q", "-x", "--no-header"), RiskClass.READ),
    "ruff.check": (("ruff", "check", "."), RiskClass.READ),
    "terraform.validate": (("terraform", "validate", "-no-color"), RiskClass.READ),
    "terraform.fmt": (("terraform", "fmt", "-check", "-recursive"), RiskClass.READ),
    "kubectl.diff": (("kubectl", "diff", "-f"), RiskClass.READ),
    "kubectl.rollout.undo": (("kubectl", "rollout", "undo"), RiskClass.ACT_REVERSIBLE),
    "kubectl.rollout.status": (("kubectl", "rollout", "status"), RiskClass.READ),
}

_SAFE_ENV_KEYS = ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "TERM")
_FORBIDDEN_ARG_CHARS = set(";&|`$<>\n")


def _validate_args(args: list[str]) -> list[str]:
    for arg in args:
        if not isinstance(arg, str):
            raise ValueError("command arguments must be strings")
        if set(arg) & _FORBIDDEN_ARG_CHARS:
            raise ValueError(f"argument contains shell metacharacters: {arg!r}")
        if arg.startswith("-") and arg not in ("-n", "-k", "--", "-f", "-l"):
            raise ValueError(f"flags are fixed by the allow-list, refusing {arg!r}")
    return args


def run_command(
    name: str, args: list[str], workspace: Path, timeout_s: int = 300
) -> dict[str, Any]:
    """Run one allow-listed command. Returns exit code, stdout and stderr (bounded)."""
    if name not in ALLOWED_COMMANDS:
        raise PermissionError(f"command '{name}' is not on the allow-list")
    prefix, _risk = ALLOWED_COMMANDS[name]
    argv = [*prefix, *_validate_args(list(args))]
    env = {k: v for k, v in os.environ.items() if k in _SAFE_ENV_KEYS}
    env["GIT_TERMINAL_PROMPT"] = "0"
    try:
        proc = subprocess.run(  # noqa: S603 # nosec B603
            argv,
            cwd=workspace,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
    except FileNotFoundError:
        return {"exit_code": 127, "stdout": "", "stderr": f"{argv[0]}: not installed", "argv": argv}
    except subprocess.TimeoutExpired:
        return {
            "exit_code": 124,
            "stdout": "",
            "stderr": f"timeout after {timeout_s}s",
            "argv": argv,
        }
    return {
        "exit_code": proc.returncode,
        "stdout": proc.stdout[-20_000:],
        "stderr": proc.stderr[-10_000:],
        "argv": argv,
        "command": shlex.join(argv),
    }


def register_sandbox_tools(registry: ToolRegistry) -> None:
    """One tool per allow-listed command, each with its own risk class."""
    for name, (prefix, risk) in ALLOWED_COMMANDS.items():

        def _fn(a: dict[str, Any], ctx: ToolContext, name: str = name) -> Any:
            if ctx.dry_run and ALLOWED_COMMANDS[name][1] >= RiskClass.ACT_REVERSIBLE:
                return {"dry_run": True, "command": name, "args": list(a.get("args", []))}
            return run_command(
                name, list(a.get("args", [])), ctx.workspace, int(a.get("timeout_s", 300))
            )

        registry.register(
            FunctionTool(
                ToolSpec(
                    name=f"exec.{name}",
                    description=f"Run `{' '.join(prefix)}` in the workspace",
                    risk=risk,
                    classification=DataClass.CONFIDENTIAL,
                    parameters={
                        "type": "object",
                        "properties": {
                            "args": {"type": "array", "items": {"type": "string"}},
                            "timeout_s": {"type": "integer"},
                        },
                    },
                ),
                _fn,
            )
        )
