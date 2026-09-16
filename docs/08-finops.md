# FinOps

!!! tip "In plain words"
    Language models are billed by the word, in and out. An agent that reads a big diff and writes a long review costs a few cents; an agent stuck in a loop could cost a lot. Regent gives every run a hard spending limit, chooses cheaper models when a job does not need the expensive one, reuses what it already sent, and counts every cent by agent so a team can see its bill.

## Cost model

Prices used for estimates (`PRICES_PER_MTOK` in `regent/gateway/providers.py`, USD per million tokens; update there when the provider changes them):

| Tier | Model | Input | Output | Cached input (≈ ×0.1) |
|---|---|---|---|---|
| `fast` | `claude-haiku-4-5` | 1.00 | 5.00 | 0.10 |
| `balanced` | `claude-sonnet-5` | 2.00 | 10.00 | 0.20 |
| `deep` | `claude-opus-5` | 5.00 | 25.00 | 0.50 |
| local | any OpenAI-compatible | 0 (infrastructure cost instead) | 0 | — |

`estimate_usd(model, input, output, cache_read)` is computed per call and stored in the ledger (`usd`) and the metric `regent_llm_usd_total`.

## Budgets

Per run, in the mandate (`budget`): `max_llm_calls`, `max_tool_calls`, `max_input_tokens`, `max_output_tokens`, `max_usd`, `max_duration_s`. `BudgetMeter` charges after every call and stops the run (`budget_exceeded`) as soon as a ceiling is crossed. `policy-check` refuses any mandate over 20 USD per run.

Shipped defaults: `pr-reviewer` 1.5 USD / 4 calls, `ci-triage` 1.0 / 4, `iac-guardian` 3.0 / 6, `incident-triage` 2.0 / 4, `dependency-steward` 0.5 / 3, `release-scribe` 0.3 / 2.

## Tiers and degradation

Mandates name a **tier**, not a model ([ADR-0005](adr/ADR-0005-model-tiers.md)). The router maps tiers to models in one place and **degrades to `fast`** when the remaining budget of the run is under 0.10 USD (`degraded: true` in the `llm.call` event). The critic never runs on a cheaper tier than the author.

Rule of thumb for choosing a tier: `fast` for classification and extraction on short inputs (steward, scribe); `balanced` for reading code and logs (reviewer, triage); `deep` when a wrong answer is expensive and the input is large (IaC fixes, incidents).

## Prompt caching

The system prompt (template + skills) is marked cacheable in the Anthropic provider (`cache_control: ephemeral`). It is stable across runs of the same agent, so repeated runs pay roughly a tenth of the input price for it. Volatile content (the diff, the logs) is in the user turn, after the cached prefix. `cache_read_tokens` is in every `llm.call` event; a zero across repeated runs means something volatile crept into the system prompt.

## Token accounting

`regent_llm_tokens_total{agent, model, direction}` and the per-run `usage` in the record (`input_tokens`, `output_tokens`, `cache_read_tokens`, `cache_write_tokens`, `usd`, `llm_calls`, `tool_calls`). Inputs are bounded at the source: diffs 120 k chars, logs 20 k per job (tail), files 60 k.

## Chargeback

The ledger's `run.started` carries the repository; join `llm.call` events on `run_id` to get spend per repository, team or cost centre. Export daily to the FinOps tool of choice; the same query gives cost per *completed* run, which is the number to optimise (a cheaper model that needs a retry is not cheaper).

## Guard rails against runaway spend

| Guard | Mechanism |
|---|---|
| Per-run ceiling | `Budget.max_usd`, `max_llm_calls` |
| Per-run time | `max_duration_s` |
| Loop protection | `rerun_at_most_once` check; agents are single-pass (no autonomous tool loop) |
| Global | Provider-side spend limits and alerts on `regent_llm_usd_total` |
| Emergency | kill switch per agent |

## Example monthly estimate

Assumptions (replace with your own): 400 PRs/month reviewed at ~0.15 USD each (balanced, 30 k input tokens, 2 k output, critic included, cache hits on the system prompt); 150 failed CI runs triaged at ~0.08 USD; 20 IaC fix runs at ~1.20 USD (deep); 60 incidents at ~0.60 USD (deep, or 0 on a local model); 200 dependency PRs at ~0.03 USD; 12 releases at ~0.02 USD.

| Workflow | Runs | Unit cost | Monthly |
|---|---|---|---|
| PR review | 400 | 0.15 | 60 |
| CI triage | 150 | 0.08 | 12 |
| IaC guardian | 20 | 1.20 | 24 |
| Incident triage | 60 | 0.60 | 36 |
| Dependency steward | 200 | 0.03 | 6 |
| Release scribe | 12 | 0.02 | ≈ 0 |
| **Total** | | | **≈ 140 USD** |

Compare with the hours of senior engineering time the same workflows consume; the ledger will replace the assumptions with measurements within the first month.
