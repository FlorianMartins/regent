# Runbook — Approve a run

**When.** A run ended with status `awaiting_approval`: a tool listed in the mandate's `requires_approval` was needed (default: `github.merge_pull_request` for `dependency-steward`).

**Symptoms.** CLI exit 1 with `status awaiting_approval` and `pending  github.merge_pull_request {'number': 42, 'method': 'squash'}`; the PR carries labels `regent:routine` and `needs-approval`; `GET /runs/{id}` shows `pending_call`.

## Steps

1. Read the run's analysis and verdict (the reason the agent wants to act):

    ```bash
    regent ledger show .regent/ledger.jsonl --run <run_id>
    # or: curl -s $REGENT/runs/<run_id> | jq '.output.analysis, .output.verdict, .pending_call'
    ```

2. Approve — which re-runs the agent with the tool pre-approved:

    === "Control plane"
        ```bash
        curl -X POST "$REGENT/runs/<run_id>/approve" -H 'content-type: application/json' \
          -d '{"approver": "alice", "tools": ["github.merge_pull_request"]}'
        ```
        `400` = the tool you approved is not the pending one; `409` = the run is not waiting.

    === "CI job"
        Re-run the same command with `--approve`, from a job step gated by a GitHub environment with required reviewers:
        ```bash
        regent run dependency-steward --repo acme/example \
          --payload '{"number": 42, "ci_green": true}' --approve github.merge_pull_request
        ```

3. The approval is written to the ledger (`approval` with `approver`, `tools`, the pending call) and the new run proceeds; the agent re-reads the PR, re-verifies and merges.

## Verification

The new run ends `succeeded`; `output.actions.merge.merged` is `true`; the PR is merged; the ledger has `approval` followed by a `tool.decision` with rule `approved`.

## Rollback

A merge is reversible: revert the PR. To stop approvals being needed on a repository (or to require them again), [change the mandate](change-a-mandate.md).
