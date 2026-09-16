"""Tool protocol and registry."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

from regent.core.models import DataClass, RiskClass, ToolResult


class ToolSpec(BaseModel):
    """Static description of a tool: what it is, what it can do, what it returns."""

    model_config = ConfigDict(frozen=True)

    name: str
    description: str
    risk: RiskClass
    classification: DataClass = DataClass.INTERNAL
    """Default classification of what the tool returns."""
    parameters: dict[str, Any] = {}
    """JSON schema of the arguments (documentation and validation)."""


@dataclass
class ToolContext:
    """What a tool may know about the run it serves."""

    run_id: str
    repository: str
    workspace: Path
    dry_run: bool = False
    """When true, tools that change state describe the change instead of making it."""
    extras: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class Tool(Protocol):
    """A callable capability with a declared risk."""

    spec: ToolSpec

    def run(self, arguments: dict[str, Any], ctx: ToolContext) -> ToolResult:
        """Execute with validated arguments."""
        ...


class FunctionTool:
    """Wrap a plain function as a tool."""

    def __init__(
        self,
        spec: ToolSpec,
        fn: Callable[[dict[str, Any], ToolContext], Any],
    ) -> None:
        self.spec = spec
        self._fn = fn

    def run(self, arguments: dict[str, Any], ctx: ToolContext) -> ToolResult:
        """Call the function; exceptions become ``ok=False`` results, never crashes."""
        try:
            output = self._fn(arguments, ctx)
        except Exception as exc:
            return ToolResult(
                call_id="", tool=self.spec.name, ok=False, error=f"{type(exc).__name__}: {exc}"
            )
        return ToolResult(
            call_id="",
            tool=self.spec.name,
            ok=True,
            output=output,
            classification=self.spec.classification,
        )


class ToolRegistry:
    """Name → tool. Registering the same name twice is a programming error."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """Add a tool."""
        if tool.spec.name in self._tools:
            raise ValueError(f"tool '{tool.spec.name}' is already registered")
        self._tools[tool.spec.name] = tool

    def get(self, name: str) -> Tool:
        """Fetch by name."""
        try:
            return self._tools[name]
        except KeyError:
            raise KeyError(f"unknown tool '{name}'") from None

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    def __iter__(self) -> Iterator[Tool]:
        return iter(self._tools.values())

    def specs(self) -> list[ToolSpec]:
        """Every registered spec, sorted by name."""
        return sorted((t.spec for t in self._tools.values()), key=lambda s: s.name)
