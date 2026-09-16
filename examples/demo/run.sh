#!/usr/bin/env bash
# Regent in 60 seconds — no API key, no network, no cloud account.
#
# The IaC guardian runs under its mandate (L2_PROPOSE): it scans a vulnerable
# Terraform module with CloudGuard-IaC, asks the model for a minimal fix (here
# a *recorded* answer, so the demo is deterministic and free), writes the fix
# to a scratch workspace, re-scans to prove the findings are gone, passes the
# independent verifier, and describes the draft PR it would open (dry run).
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="$(cd "$here/../.." && pwd)"
bin="$root/.venv/bin"
[ -x "$bin/regent" ] || bin="$(dirname "$(command -v regent)")"

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
cp "$here/vulnerable/main.tf" "$work/main.tf"

echo "▶ 1/3  CloudGuard-IaC on the vulnerable module (expected: findings)"
"$bin/cloudguard" scan-iac "$work/main.tf" --fail-on never --no-color || true
echo
echo "▶ 2/3  regent run iac-guardian  (provider: replay, dry run)"
REGENT_PROVIDER=replay \
REGENT_REPLAY_FILE="$here/replay.json" \
REGENT_LEDGER="$work/ledger.jsonl" \
REGENT_MANDATES_DIR="$root/policies/mandates" \
"$bin/regent" run iac-guardian \
  --repo acme/demo --env dev --workspace "$work" --dry-run \
  --event demo --payload '{"paths": ["main.tf"], "head": "regent/iac-fix-demo", "base": "main"}'
echo
echo "▶ 3/3  CloudGuard-IaC on the fixed module (expected: clean)"
"$bin/cloudguard" scan-iac "$work/main.tf" --no-color
echo
echo "▶ Audit trail — every decision is in the hash-chained ledger"
"$bin/regent" ledger show "$work/ledger.jsonl" --last 12
"$bin/regent" ledger verify "$work/ledger.jsonl"
