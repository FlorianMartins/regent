# Runbook — Change a mandate

**When.** Widen (more autonomy, more tools, bigger budget, higher `max_remote_class`, lifting an approval) or narrow (the opposite) what an agent may do on some scope.

**Rule of thumb.** Narrowing can be done by the platform on-call alone; widening is a PR reviewed by security with the numbers that justify it (acceptance rate, rejection rate, incidents).

## Steps

1. Edit or add a document in `policies/mandates/`. Prefer a **scoped override** to editing defaults:

    ```yaml
    - agent: ci-triage
      scopes: ["acme/internal-*"]
      environments: ["dev", "staging"]
      autonomy: L3_ACT_REVERSIBLE
      model_tier: balanced
      allowed_tools: ["github.get_workflow_run", "github.get_job_logs", "github.comment",
                      "github.create_issue", "github.rerun_failed_jobs"]
      max_remote_class: CONFIDENTIAL
      verification: required
      budget: { max_llm_calls: 4, max_usd: 1.0, max_duration_s: 600 }
    ```

    Resolution: the most specific `scopes`/`environments` win; on a tie the last file loaded (alphabetical) wins.

2. Validate:

    ```bash
    regent policy-check                                     # invariants
    regent mandates --agent ci-triage --repo acme/internal-api --env dev   # what will apply
    regent evals                                            # nothing else broke
    ```

3. Open the PR; CODEOWNERS requires platform + security for `policies/`.
4. Merge; the control plane reloads on restart (or the ConfigMap rollout); CI jobs pick it up at checkout.

## Verification

The next run's `run.started` event shows `mandate.source` = your file and the expected `autonomy`; `regent_tool_calls_total{decision="deny"}` for that agent does not rise (a rise means a tool is missing from the allow-list).

## Rollback

Revert the PR. A rollback that *narrows* needs no review.
