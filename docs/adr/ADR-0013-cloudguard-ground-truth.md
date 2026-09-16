# ADR-0013 — CloudGuard-IaC is the ground truth for IaC fixes

**Status:** Accepted (2026-09)

## Context

A model asked to fix a security finding will produce something that *looks* right. Whether the finding is actually gone is a question a deterministic scanner answers better than a model.

## Decision

The IaC guardian's deterministic check `cloudguard_clean_after_fix` writes the proposed files into the workspace and **re-runs `cloudguard.scan`**; every rule id a change claims to resolve must be absent from the re-scan. The check `changes_only_flagged_files` refuses edits elsewhere. Only then does the critic run, and only then is a draft PR opened. CloudGuard is consumed as a library (`cloudguard.engine.scan_paths`), pinned as a dependency.

## Consequences

- The model never grades its own homework; the PR body shows before/after counts.
- The guardian's fixes are limited to what CloudGuard can detect (31 rules today); other scanners can be added as tools with the same pattern.
- A dry run skips the re-scan and says so in the check detail.

## Alternatives considered

- **Trusting the model's `resolves` claim** — rejected.
- **Human-only verification** — keeps the toil the agent exists to remove; the human still reviews the PR.
