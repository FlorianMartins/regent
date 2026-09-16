"""Prompts as code.

A prompt is a versioned artefact, like a schema or a migration. Each template
lives in ``regent/prompts/<name>.md`` with YAML front-matter and is addressed
as ``name@version``. The gateway records the id *and* the content hash in the
ledger, so a behaviour change can be traced to a prompt change, and evals can
be pinned to a version.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

_FRONT_MATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)


class PromptError(ValueError):
    """A prompt template is missing or malformed."""


@dataclass(frozen=True)
class Prompt:
    """A loaded template."""

    name: str
    version: str
    body: str
    sha256: str
    description: str = ""

    @property
    def id(self) -> str:
        """``name@version`` — what the ledger records."""
        return f"{self.name}@{self.version}"

    def render(self, **values: str) -> str:
        """Fill ``{{placeholders}}``; a missing value is an error, not an empty string."""
        out = self.body
        for key, value in values.items():
            out = out.replace("{{" + key + "}}", value)
        leftover = re.findall(r"{{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*}}", out)
        if leftover:
            raise PromptError(f"prompt {self.id}: unfilled placeholders {sorted(set(leftover))}")
        return out


def parse_prompt(name: str, text: str) -> Prompt:
    """Parse front-matter (``version``, ``description``) and body."""
    match = _FRONT_MATTER.match(text)
    if not match:
        raise PromptError(f"prompt '{name}' has no front-matter")
    meta: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            meta[key.strip()] = value.strip().strip("\"'")
    if "version" not in meta:
        raise PromptError(f"prompt '{name}' declares no version")
    body = text[match.end() :].strip()
    return Prompt(
        name=name,
        version=meta["version"],
        body=body,
        sha256=hashlib.sha256(body.encode("utf-8")).hexdigest(),
        description=meta.get("description", ""),
    )


class PromptRegistry:
    """Loads templates from the package (default) or from a directory (override)."""

    def __init__(self, directory: Path | None = None) -> None:
        self._directory = directory
        self._cache: dict[str, Prompt] = {}

    def get(self, name: str) -> Prompt:
        """Load ``<name>.md`` once and cache it."""
        if name in self._cache:
            return self._cache[name]
        if self._directory is not None:
            path = self._directory / f"{name}.md"
            if not path.exists():
                raise PromptError(f"prompt '{name}' not found in {self._directory}")
            text = path.read_text(encoding="utf-8")
        else:
            try:
                text = resources.files("regent.prompts").joinpath(f"{name}.md").read_text("utf-8")
            except (FileNotFoundError, ModuleNotFoundError) as exc:
                raise PromptError(f"prompt '{name}' is not shipped with the package") from exc
        prompt = parse_prompt(name, text)
        self._cache[name] = prompt
        return prompt

    def names(self) -> list[str]:
        """Every template available."""
        if self._directory is not None:
            return sorted(p.stem for p in self._directory.glob("*.md"))
        return sorted(
            p.name[:-3]
            for p in resources.files("regent.prompts").iterdir()
            if p.name.endswith(".md")
        )
