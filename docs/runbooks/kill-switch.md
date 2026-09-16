# Runbook — Kill switch

**When.** An agent must stop acting *now*: it posts wrong things, re-runs jobs it should not, a prompt or model regression is suspected, or security asks for it. Seconds matter; no second reviewer is needed to *reduce* autonomy.

**Symptoms.** Complaints from developers; `regent_verifications_total{verdict="rejected"}` spiking; unexpected `tool.call` events; a spend alert.

## Steps

1. Add a mandate document with the kill switch for the agent. Any matching document with `kill_switch: true` wins, so the smallest possible file is enough:

    ```yaml
    # policies/mandates/zz-kill-switch.yaml
    - agent: ci-triage
      kill_switch: true
    ```

2. Deliver it:
    - **Control plane:** the mandates directory is a ConfigMap/volume at `REGENT_MANDATES_DIR`; apply the change (or merge the PR the Argo application watches). The store is loaded per process start — restart the pods (`kubectl rollout restart deploy/regent-api`).
    - **CI jobs:** merge the file to the default branch; every subsequent job picks it up at checkout. For in-flight runs, cancel the workflow.
3. Confirm:

    ```bash
    regent policy-check
    regent mandates --agent ci-triage --repo acme/example
    # → "kill_switch": true
    ```

## Verification

The next run for that agent ends with status `denied`, error `agent disabled by kill switch`, ledger `run.finished` with `status: denied`; metric `regent_runs_total{agent="ci-triage",status="denied"}` increments. Nothing is written to GitHub.

## Rollback

Delete the file (or set `kill_switch: false`) through the normal mandate PR path; re-enabling **is** a widening and needs the usual review. Watch the rejection rate for a day after.
