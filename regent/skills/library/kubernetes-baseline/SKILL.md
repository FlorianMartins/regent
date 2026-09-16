---
name: kubernetes-baseline
version: "1"
description: Pod security baseline enforced by admission policies.
applies_to: [pr-reviewer, incident-triage]
---
Workloads must: run as non-root (`runAsNonRoot: true`), drop all capabilities, use a read-only root filesystem, set CPU and memory requests and limits, pin images by digest or immutable tag (never `latest`), declare readiness and liveness probes, and carry a NetworkPolicy. The admission layer (OPA Gatekeeper / Conftest in CI) rejects manifests that do not; a review finding on these points is therefore "high", not "style".
