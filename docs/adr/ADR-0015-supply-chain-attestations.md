# ADR-0015 — SBOM, keyless signature and SLSA provenance on releases

**Status:** Accepted (2026-09)

## Context

Regent enforces supply-chain hygiene on other repositories (scanners, pinned images). Its own artefacts must be verifiable by a stranger with a command.

## Decision

The release workflow builds the wheel and the container image; generates an **SBOM** (Syft, SPDX); scans the image (Trivy, blocking above the threshold); attests **SLSA build provenance** (`actions/attest-build-provenance`) for the image digest and the wheel; **signs** the image with **cosign keyless** using the workflow's GitHub OIDC identity; attaches SBOM and provenance to the GitHub release. Actions are pinned and Dependabot-maintained; OpenSSF Scorecard and CodeQL run on schedule. Target: **SLSA Build L2**.

## Consequences

- `gh attestation verify` and `cosign verify` prove which workflow built which commit into which digest, without any key material in the repository.
- L3 (isolated, non-falsifiable builds) would require the SLSA reusable generators and stricter runner isolation; planned once the release cadence is stable.
- Badges on the README point at verifiable artefacts, not at claims.

## Alternatives considered

- **Key-based signing** — a key to store, rotate and leak.
- **No attestations** — inconsistent with a platform that gates others on them.
