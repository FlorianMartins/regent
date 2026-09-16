# Runbook — Rotate credentials

**When.** A credential may have been exposed (a redaction kind appeared where it should not, a laptop was lost, a log leaked), or on the rotation schedule (quarterly).

Credentials Regent uses: `ANTHROPIC_API_KEY`, `GITHUB_TOKEN` (job token or GitHub App installation token), `GITHUB_WEBHOOK_SECRET`, `ALERTMANAGER_WEBHOOK_TOKEN`, `REGENT_LOCAL_KEY` (optional), the GitHub App private key.

## Steps

1. **Anthropic API key**: create a new key in the provider console; update the secret manager entry (Secrets Manager / Vault); External Secrets Operator syncs it; restart pods if the operator does not trigger a rollout:

    ```bash
    kubectl -n regent rollout restart deploy/regent-api
    ```

    For CI: update the GitHub Actions secret. Revoke the old key **after** the new one is confirmed (step "Verification").
2. **GitHub App private key**: generate a new key in the App settings; store it; restart; delete the old key in the App settings.
3. **Webhook secret**: generate a new random value; update the secret manager and the webhook configuration on GitHub in the same change window (webhooks signed with the old secret return `401` in between — GitHub retries).
4. **Alertmanager token**: same, on the Alertmanager receiver configuration.
5. Check the ledger for evidence of the exposure path:

    ```bash
    jq -c 'select(.kind=="llm.call" and (.data.redactions|length>0)) | {run_id, redactions: .data.redactions}' .regent/ledger.jsonl
    ```

    Redaction kinds tell you a credential shape was *about to leave*; the value never did.

## Verification

```bash
REGENT_PROVIDER=anthropic regent run release-scribe --repo acme/example \
  --payload '{"base":"v1.0.0","head":"v1.1.0"}' --dry-run
```

succeeds (status `succeeded`) with the new key; `GET /healthz` is fine; a signed test webhook returns `202`.

## Rollback

Keep the previous key valid until verification passes; if the new one fails, switch the secret back and investigate. Never leave two Anthropic keys valid longer than the change window.
