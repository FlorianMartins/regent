"""Assemble a :class:`~regent.runtime.runner.Platform` from configuration.

One place decides which provider, which tools and which mandates are in play.
The CLI, the API server and the tests all build their platform here, so a
setting cannot be right in one and wrong in another.

Configuration comes from environment variables (12-factor):

``REGENT_PROVIDER``        ``anthropic`` (default) | ``local`` | ``replay``
``REGENT_REPLAY_FILE``     fixture file for the replay provider
``REGENT_LOCAL_URL``       base URL of the OpenAI-compatible local model
``REGENT_LOCAL_MODEL``     model name served locally (used for every tier)
``REGENT_MANDATES_DIR``    directory of mandate YAML files (default ``policies/mandates``)
``REGENT_LEDGER``          path of the ledger file (default ``.regent/ledger.jsonl``)
``REGENT_SKILLS_DIR``      optional directory of organisation skills
``REGENT_PROMPTS_DIR``     optional directory overriding packaged prompts
``ANTHROPIC_API_KEY``      credential for the Anthropic provider
``GITHUB_TOKEN``           credential for the GitHub tools
"""

from __future__ import annotations

import os
from pathlib import Path

from regent.agents.ci_triage import CITriage
from regent.agents.dependency_steward import DependencySteward
from regent.agents.iac_guardian import IaCGuardian
from regent.agents.incident_triage import IncidentTriage
from regent.agents.pr_reviewer import PRReviewer
from regent.agents.release_scribe import ReleaseScribe
from regent.core.ledger import Ledger
from regent.core.policy import MandateStore
from regent.gateway.gateway import Gateway
from regent.gateway.prompts import PromptRegistry
from regent.gateway.providers import (
    AnthropicProvider,
    OpenAICompatibleProvider,
    Provider,
    ReplayProvider,
)
from regent.gateway.router import Router
from regent.runtime.runner import Platform
from regent.skills import SkillRegistry
from regent.tools.base import ToolRegistry
from regent.tools.cloudguard_tool import register_cloudguard_tools
from regent.tools.github import GitHubClient, register_github_tools
from regent.tools.observability_tools import register_observability_tools
from regent.tools.sandbox import register_sandbox_tools
from regent.tools.workspace import register_workspace_tools

DEFAULT_AGENTS = (
    PRReviewer,
    CITriage,
    IaCGuardian,
    IncidentTriage,
    DependencySteward,
    ReleaseScribe,
)


class ConfigError(ValueError):
    """The environment does not describe a usable platform."""


def build_provider(kind: str | None = None) -> tuple[Provider, Provider | None, Router]:
    """Return ``(default provider, local provider or None, router)`` from the env."""
    kind = (kind or os.environ.get("REGENT_PROVIDER", "anthropic")).lower()
    local_url = os.environ.get("REGENT_LOCAL_URL")
    local_model = os.environ.get("REGENT_LOCAL_MODEL", "local")
    local: Provider | None = (
        OpenAICompatibleProvider(local_url, os.environ.get("REGENT_LOCAL_KEY", ""))
        if local_url
        else None
    )
    if kind == "replay":
        fixture = os.environ.get("REGENT_REPLAY_FILE")
        provider: Provider = (
            ReplayProvider.from_file(Path(fixture)) if fixture else ReplayProvider()
        )
        return provider, local, Router()
    if kind == "local":
        if local is None:
            raise ConfigError("REGENT_PROVIDER=local needs REGENT_LOCAL_URL")
        tiers = {"fast": local_model, "balanced": local_model, "deep": local_model}
        return local, None, Router(tiers)
    if kind == "anthropic":
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise ConfigError(
                "ANTHROPIC_API_KEY is not set (or choose REGENT_PROVIDER=replay|local)"
            )
        return AnthropicProvider(), local, Router()
    raise ConfigError(f"unknown REGENT_PROVIDER '{kind}'")


def build_tools(github: GitHubClient | None = None) -> ToolRegistry:
    """Every tool the shipped agents can ask for."""
    registry = ToolRegistry()
    register_github_tools(registry, github or GitHubClient())
    register_cloudguard_tools(registry)
    register_workspace_tools(registry)
    register_sandbox_tools(registry)
    register_observability_tools(registry)
    return registry


def build_platform(
    *,
    provider: str | None = None,
    mandates_dir: Path | None = None,
    ledger_path: Path | None = None,
    tools: ToolRegistry | None = None,
) -> Platform:
    """Wire everything from the environment, with explicit overrides for tests."""
    default, local, router = build_provider(provider)
    ledger_env = os.environ.get("REGENT_LEDGER", ".regent/ledger.jsonl")
    ledger = Ledger(ledger_path if ledger_path is not None else Path(ledger_env))
    gateway = Gateway(default, router=router, local_provider=local)
    mandates_path = mandates_dir or Path(os.environ.get("REGENT_MANDATES_DIR", "policies/mandates"))
    if not mandates_path.is_dir():
        raise ConfigError(f"mandates directory not found: {mandates_path}")
    store = MandateStore.from_directory(mandates_path)
    skills_dir = os.environ.get("REGENT_SKILLS_DIR")
    prompts_dir = os.environ.get("REGENT_PROMPTS_DIR")
    platform = Platform(
        gateway=gateway,
        tools=tools or build_tools(),
        mandates=store,
        ledger=ledger,
        prompts=PromptRegistry(Path(prompts_dir) if prompts_dir else None),
        skills=SkillRegistry(Path(skills_dir) if skills_dir else None),
        agents=[cls() for cls in DEFAULT_AGENTS],
    )
    return platform
