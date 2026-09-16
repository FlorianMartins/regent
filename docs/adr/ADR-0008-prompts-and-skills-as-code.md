# ADR-0008 — Prompts and skills are versioned code

**Status:** Accepted (2026-09)

## Context

Prompt changes change behaviour as much as code changes do, and organisation-specific rules (Terraform baseline, incident wording, dependency policy) must be the same for every agent and reviewable by the teams that own them.

## Decision

Prompts are `regent/prompts/<name>.md` with front-matter (`version`, `description`); addressed as `name@version`; sha256 of the body recorded on every `llm.call`; unfilled placeholders are errors. Skills are `SKILL.md` directories (`name`, `version`, `applies_to`, `checks`) composed into the system prompt; ids and sha256 recorded in `run.started`. Both can be overridden per organisation via `REGENT_PROMPTS_DIR` / `REGENT_SKILLS_DIR` without forking. Changes ship with eval cases (ADR-0016).

## Consequences

- A behaviour change is traceable to a prompt or skill version and date.
- Non-engineers can review rules in Markdown; the checks a skill declares are enforced by code.
- No prompt UI; that is a feature for a platform reviewed in pull requests.

## Alternatives considered

- **Prompts in Python strings** — no version, no hash, no review by domain owners.
- **Prompt-management SaaS** — runtime dependency and a second source of truth.
