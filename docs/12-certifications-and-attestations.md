# Certifications and attestations

!!! tip "In plain words"
    A badge on a README is a claim. An attestation is a claim you can *check* yourself with a command, because it was signed by something that cannot be faked easily (here, GitHub's own identity for the workflow that built the software). This page lists every claim the repository makes, what it proves, how you verify it, and — just as important — what it does not prove.

## Summary

| Claim | Proves | Verify with |
|---|---|---|
| CI green | Lint, strict types, 117 tests, SAST, secrets scan, IaC scan, policy check, evals, build all passed on the commit | The Actions tab; the required status check on `main` |
| SLSA build provenance | The image/wheel digest was produced by *this* repository's release workflow from *this* commit | `gh attestation verify` |
| Keyless signature (cosign) | The image was signed by the workflow's OIDC identity, not by a person | `cosign verify` |
| SBOM | Exact inventory of packages in the image | Download from the release / `cosign download sbom` |
| Trivy scan | No known CVE above the threshold at build time | CI job log; the SARIF in the Security tab |
| CodeQL | Semantic analysis of the Python code found nothing blocking | Security tab → Code scanning |
| OpenSSF Scorecard | Repository practices (branch protection, pinned dependencies, signed releases, tokens permissions…) | Scorecard badge → report |
| Dependabot | Dependencies and Actions are kept current | `.github/dependabot.yml`; open PRs |
| CloudGuard-IaC self-scan | The platform's own Terraform and Dockerfile pass the scanner it ships as a tool | CI job |

## Verify the provenance (SLSA)

```bash
# Container image published by the release workflow
gh attestation verify oci://ghcr.io/florianmartins/regent:<tag> --owner FlorianMartins

# A released wheel
gh attestation verify regent_platform-<version>-py3-none-any.whl --owner FlorianMartins
```

A successful verification prints the workflow, the commit and the builder. It fails for an image built anywhere else, even from the same source.

## Verify the signature (cosign, keyless)

```bash
cosign verify ghcr.io/florianmartins/regent:<tag> \
  --certificate-identity-regexp 'https://github.com/FlorianMartins/regent/.github/workflows/.*' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com
```

Keyless signing means there is no private key to steal: the signature binds the image digest to the workflow identity issued by GitHub's OIDC provider, recorded in the Sigstore transparency log.

## Get the SBOM

```bash
cosign download sbom ghcr.io/florianmartins/regent:<tag> > sbom.spdx.json
grype sbom:sbom.spdx.json          # re-scan it yourself, today, not at build time
```

## The CI gates, in order

1. **Quality** — `ruff` (lint + format), `mypy --strict`, `actionlint` on the workflows.
2. **Tests** — `pytest` on every supported Python version with coverage ≥ 80 % (`fail_under` in `pyproject.toml`).
3. **SAST & dependencies** — `bandit` (blocking), `pip-audit` (blocking), `semgrep` (advisory), `gitleaks`.
4. **Policies** — `regent policy-check`; CloudGuard-IaC on `infra/`; Conftest on manifests and Terraform.
5. **Evals** — `regent evals` offline.
6. **Build** — wheel + sdist, `twine check`, smoke-tested in a clean venv.
7. **Container** — image built, scanned by Trivy, SBOM by Syft, provenance attested, signed on `main`/tags.
8. **Docs** — `mkdocs build --strict`, published to GitHub Pages.
9. **One required check** (`CI complete`) that the branch protection needs.

## What these do NOT prove

- That the agents are *correct* on your codebase: evals are offline fixtures and a nightly live run on the author's cases, not on yours. Onboard at L0/L1 and measure.
- That the LLM provider handles data as you need: that is a contract (DPA) between you and the provider; Regent's classification controls only what is sent.
- That there is no vulnerability: scanners find known classes of problems at a point in time. Re-scan the SBOM regularly (`grype`) — CVEs are published after builds.
- That the ledger cannot be destroyed: it is tamper-*evident*, not indestructible. Ship it to write-once storage.
- SLSA L3 or L4: the target is L2 (hosted build with signed provenance). See [ADR-0015](adr/ADR-0015-supply-chain-attestations.md) for what L3 would take.
