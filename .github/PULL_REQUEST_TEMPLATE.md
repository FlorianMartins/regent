## What this changes

<!-- One or two sentences. Link the issue it closes: Closes #123 -->

## Why

<!-- The problem being solved. For an agent change: what the agent got wrong, with the run id. -->

## Checklist

- [ ] `make check` is green (lint, types, tests, SAST, IaC scan, policy, evals, docs)
- [ ] New behaviour is covered by a test
- [ ] **Mandate change** (`policies/mandates/`): I said what the agent can now do that it could not before, and why that is acceptable
- [ ] **Prompt change** (`regent/prompts/`): `version` bumped **and** an eval case added or updated under `evals/cases/`
- [ ] **Skill change** (`regent/skills/library/`): `version` bumped; every declared `check` is implemented by an agent
- [ ] **New tool**: risk class and data classification declared honestly; a `dry_run` path exists for anything that writes
- [ ] **Infrastructure change**: `make iac-scan` and the Conftest policies pass
- [ ] For a behaviour change: `CHANGELOG.md` updated under `[Unreleased]`

## How it was verified

<!-- The commands you ran and what they returned. "Tests pass" is not a verification.
     For agent changes, paste the relevant `regent evals` lines. -->
