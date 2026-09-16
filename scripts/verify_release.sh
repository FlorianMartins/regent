#!/usr/bin/env bash
# Verify a Regent release the way a consumer should, before running it.
#
#   scripts/verify_release.sh v0.1.0
#
# Checks, in order:
#   1. the container image signature (cosign, keyless — signed by this repo's release workflow)
#   2. the SLSA build provenance of the image (GitHub attestations)
#   3. the SBOM attestation of the image
#   4. the SLSA build provenance of the wheel attached to the GitHub release
#
# Needs: cosign, gh (authenticated), curl. Nothing is executed from the release.
set -euo pipefail

TAG="${1:?usage: $0 vX.Y.Z}"
OWNER="${OWNER:-FlorianMartins}"
REPO="${REPO:-regent}"
IMAGE="${IMAGE:-ghcr.io/florianmartins/regent}"
VERSION="${TAG#v}"

for tool in cosign gh curl; do
  command -v "$tool" >/dev/null || { echo "missing: $tool" >&2; exit 2; }
done

echo "▶ resolving the digest of ${IMAGE}:${VERSION}"
DIGEST="$(cosign triangulate --type digest "${IMAGE}:${VERSION}" 2>/dev/null || true)"
if [ -z "$DIGEST" ]; then
  DIGEST="$(docker buildx imagetools inspect "${IMAGE}:${VERSION}" --format '{{json .Manifest.Digest}}' | tr -d '"')"
fi
echo "  ${DIGEST}"

echo "▶ 1/4 cosign signature"
cosign verify "${IMAGE}@${DIGEST}" \
  --certificate-identity-regexp "^https://github.com/${OWNER}/${REPO}/.github/workflows/release.yml@" \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com >/dev/null
echo "  ✓ signed by the release workflow of ${OWNER}/${REPO}"

echo "▶ 2/4 SLSA provenance of the image"
gh attestation verify "oci://${IMAGE}@${DIGEST}" --owner "${OWNER}"

echo "▶ 3/4 SBOM attestation of the image"
gh attestation verify "oci://${IMAGE}@${DIGEST}" --owner "${OWNER}" \
  --predicate-type https://spdx.dev/Document/v2.3

echo "▶ 4/4 provenance of the wheel"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
gh release download "${TAG}" --repo "${OWNER}/${REPO}" --pattern '*.whl' --dir "$WORK"
gh attestation verify "$WORK"/*.whl --owner "${OWNER}"

echo "✅ release ${TAG} verified: signature, provenance, SBOM, wheel"
