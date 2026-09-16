"""Load and compose skills."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

import yaml

_FRONT_MATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)


class SkillError(ValueError):
    """A skill is missing or malformed."""


@dataclass(frozen=True)
class Skill:
    """One loaded skill."""

    name: str
    version: str
    description: str
    body: str
    sha256: str
    applies_to: tuple[str, ...] = ("*",)
    """Agent names (glob) that load this skill by default."""
    checks: tuple[str, ...] = ()
    """Deterministic check ids the verifier must run when this skill is active."""

    @property
    def id(self) -> str:
        """``name@version``."""
        return f"{self.name}@{self.version}"


def parse_skill(name: str, text: str) -> Skill:
    """Parse ``SKILL.md`` content."""
    match = _FRONT_MATTER.match(text)
    if not match:
        raise SkillError(f"skill '{name}' has no front-matter")
    try:
        meta = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError as exc:
        raise SkillError(f"skill '{name}': invalid front-matter: {exc}") from exc
    if not isinstance(meta, dict) or "version" not in meta:
        raise SkillError(f"skill '{name}' declares no version")
    body = text[match.end() :].strip()
    return Skill(
        name=str(meta.get("name", name)),
        version=str(meta["version"]),
        description=str(meta.get("description", "")),
        body=body,
        sha256=hashlib.sha256(body.encode("utf-8")).hexdigest(),
        applies_to=tuple(meta.get("applies_to", ["*"])),
        checks=tuple(meta.get("checks", [])),
    )


class SkillRegistry:
    """Skills from the packaged library, optionally overlaid by a directory."""

    def __init__(self, directory: Path | None = None) -> None:
        self._directory = directory
        self._skills: dict[str, Skill] = {}
        self._load_package()
        if directory is not None:
            self._load_directory(directory)

    def _load_package(self) -> None:
        try:
            root = resources.files("regent.skills.library")
        except ModuleNotFoundError:
            return
        for entry in root.iterdir():
            if entry.is_dir():
                skill_file = entry.joinpath("SKILL.md")
                if skill_file.is_file():
                    skill = parse_skill(entry.name, skill_file.read_text("utf-8"))
                    self._skills[skill.name] = skill

    def _load_directory(self, directory: Path) -> None:
        for skill_file in sorted(directory.glob("*/SKILL.md")):
            skill = parse_skill(skill_file.parent.name, skill_file.read_text("utf-8"))
            self._skills[skill.name] = skill

    def get(self, name: str) -> Skill:
        """Fetch one skill."""
        try:
            return self._skills[name]
        except KeyError:
            raise SkillError(f"unknown skill '{name}'") from None

    def names(self) -> list[str]:
        """Every skill name."""
        return sorted(self._skills)

    def for_agent(self, agent: str, extra: tuple[str, ...] = ()) -> list[Skill]:
        """Skills that apply to *agent* by default, plus *extra* by name."""
        import fnmatch

        chosen: dict[str, Skill] = {}
        for skill in self._skills.values():
            if any(fnmatch.fnmatchcase(agent, pattern) for pattern in skill.applies_to):
                chosen[skill.name] = skill
        for name in extra:
            chosen[name] = self.get(name)
        return [chosen[k] for k in sorted(chosen)]

    @staticmethod
    def compose(skills: list[Skill]) -> str:
        """Render skills as one Markdown section for a system prompt."""
        if not skills:
            return ""
        parts = ["# Skills in force", ""]
        for skill in skills:
            parts.append(f"## {skill.name} (v{skill.version})")
            parts.append(skill.body)
            parts.append("")
        return "\n".join(parts).strip()
