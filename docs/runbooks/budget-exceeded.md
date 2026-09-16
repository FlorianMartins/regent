# Runbook — Budget exceeded

**When.** Runs end with status `budget_exceeded`, or the spend dashboard/alert on `regent_llm_usd_total` fires.

**Symptoms.** CLI output `status budget_exceeded` and `detail budget exceeded on usd: … > …` (or `llm_calls`, `tool_calls`, `input_tokens`, `output_tokens`, `duration_s`); the ledger `run.finished` shows the same; no action was taken (the run stops at the ceiling).

## Steps

1. Identify the dimension and the agent from the record or:

    ```bash
    regent ledger show .regent/ledger.jsonl --last 100 | grep budget
    ```

2. Decide which it is:
    - **Input too large** (`input_tokens`): a huge diff or log. The tools already truncate (diff 120 k chars, logs 20 k per job); lower `max_chars` in the agent, or exclude vendored paths at the source.
    - **Too many calls** (`llm_calls`): a bug or a retry loop in an agent; look at the `llm.call` sequence. Shipped agents make 1 + 1 (critic) calls.
    - **Money** (`usd`): a deep-tier run on large input; check `degraded` in `llm.call` — the router already fell back to `fast` under 0.10 USD remaining.
    - **Time** (`duration_s`): a slow provider or a hanging tool; the SDK timeout is 300 s per call, sandbox commands 300 s.
3. If the budget is simply too tight for a legitimate workload, raise it in the mandate (a widening: PR + security review). `policy-check` caps `max_usd` at 20 per run.
4. If spend is globally too high, lower tiers per agent in the mandates (`model_tier: fast`) or pin the router's tier map to cheaper models, then run `regent evals --live` to confirm quality.

## Verification

The run succeeds after the change; `regent_llm_usd_total` daily rate returns under the forecast.

## Rollback

Revert the mandate PR; budgets are per run, so nothing else changes.
