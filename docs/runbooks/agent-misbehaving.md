# Runbook — Agent misbehaving

**When.** An agent produced a wrong, harmful or noisy result: a review with invented findings, a re-run of a real failure, a draft PR that weakens a control, an incident issue with speculation.

**Symptoms.** Developer reports; `regent_verifications_total{verdict="rejected"}` up; `tool.call` events you did not expect; a comment signed "🤖 Regent" that is wrong.

## Steps

1. **Contain**: if it can act (L2+), flip the [kill switch](kill-switch.md). At L1, you may leave it running while you investigate.
2. **Find the run**: the comment/PR body carries the agent name; find the `run_id` in the ledger by time and repository:

    ```bash
    regent ledger show .regent/ledger.jsonl --last 200 | grep -i "acme/example"
    regent ledger show .regent/ledger.jsonl --run <run_id>
    ```

    (In the control plane, `GET /runs?limit=100` then `GET /runs/{run_id}`.)

3. **Read the trail** in order: `run.started` (mandate `source`, skills and their sha256, trigger), `tool.call` (what it saw, redacted), `llm.call` (prompt id, model, tier, `degraded`, refusal), `analysis` (what it concluded), `verification` (checks and critic issues), `tool.decision`/`tool.call` in the act phase.
4. **Classify the cause**:
    - Wrong input (truncated diff, missing logs) → tool bounds; adjust or add a check.
    - Model output wrong and the critic accepted → add a **deterministic check** for that failure; consider raising the tier.
    - Critic rejected but mode was `advisory` → set `verification: required` for that agent/repository.
    - Mandate too wide → narrow it ([change a mandate](change-a-mandate.md)).
    - Prompt or skill regression → compare the sha256 with the previous run's; roll the version back.
5. **Reproduce offline**: build a replay fixture from the ledger's `analysis` output and the world it saw, as an eval case under `evals/cases/`; make it fail; fix; make it pass.
6. **Ship** the fix (prompt/skill version bump, check, or mandate) with the eval case; re-enable the agent.

## Verification

`regent evals` green with the new case; the rejection rate returns to baseline within a day; no repeat report.

## Rollback

If the fix makes things worse, revert the prompt/skill version (the ledger shows which version was in force when) and keep the kill switch until the eval case passes.
