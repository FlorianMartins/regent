# Agent catalogue

!!! tip "In plain words"
    Regent ships six specialised workers, each with one job, plus one inspector who checks all of them. Every worker has a fixed list of tools it may ask for, a level of independence written in its mandate, and a set of mechanical checks that its output must pass. This page is the staff directory.

## Reading a card

- **Autonomy** is what the *default* mandate grants (`policies/mandates/defaults.yaml`). A repository can narrow it, never widen it beyond what security reviews.
- **Tools** are exact names; the risk class is what the tool declares in code, not what the agent thinks.
- **Checks** are the deterministic tests run by the verifier before the critic; their ids appear in the ledger `verification` event.
- **Prompt id** is `name@version`; the sha256 of the prompt body is recorded with every model call.

## Summary

| Agent | Job | Autonomy (default) | Tier | Highest-risk tool | Verification |
|---|---|---|---|---|---|
| `pr-reviewer` | Advisory code review, line-anchored | L1_ADVISE | balanced | `github.create_review` (ADVISE) | required |
| `ci-triage` | Classify a failed run; re-run flaky jobs | L3_ACT_REVERSIBLE | balanced | `github.rerun_failed_jobs` (ACT_REVERSIBLE) | required |
| `iac-guardian` | Fix CloudGuard findings as a draft PR | L2_PROPOSE | deep | `github.create_pull_request` (PROPOSE) | required |
| `incident-triage` | Hypotheses, read-only diagnostics, status draft | L1_ADVISE | deep | `github.create_issue` (ADVISE) | advisory |
| `dependency-steward` | Merge routine bumps under policy | L3_ACT_REVERSIBLE (merge needs approval) | fast | `github.merge_pull_request` (ACT_REVERSIBLE) | required |
| `release-scribe` | Release notes → draft release | L2_PROPOSE | fast | `github.create_release` (PROPOSE) | advisory |

---

## `pr-reviewer`

**Purpose.** First-pass review of a pull request: correctness, security, reliability, then maintainability. Advisory only — it never approves, never requests changes, never merges.

| | |
|---|---|
| Trigger | `pull_request` opened / synchronize / ready_for_review by a human (webhook), or `regent run pr-reviewer --payload '{"number": N}'` |
| Inputs | PR metadata, unified diff (truncated at 120 000 characters, flagged) |
| Tools (risk) | `github.get_pr` (READ) · `github.get_pr_diff` (READ, CONFIDENTIAL) · `github.create_review` (ADVISE) · `github.add_labels` (ADVISE); mandate also allows `github.list_pr_files`, `github.get_file` |
| Prompt | `pr_reviewer@1` |
| Skills | `secure-review` (default) + any skill whose `applies_to` matches: `conventional-commits`, `kubernetes-baseline` |
| Output | `ReviewOutput`: summary, confidence, evidence, `findings[file, line, severity, category, title, detail, quote, suggestion]`, `diff_truncated` |
| Checks | `findings_cite_lines` (every file is in the diff) · `findings_use_known_enums` (severity ∈ critical/high/medium/low, category ∈ correctness/security/reliability/maintainability/tests) |
| Critic focus | findings that do not quote real lines, overstated severities, anything phrased as an approval or a merge decision |
| Actions | one review with event `COMMENT` and inline comments; labels `regent:critical` / `regent:high` when relevant |
| Failure modes | diff unavailable → run failed; model returns no structured review → failed; finding on a file outside the diff → verification rejects, nothing posted |
| KPIs | acceptance rate of findings, time-to-first-review, verifier rejection rate |

## `ci-triage`

**Purpose.** When a workflow fails, decide *why* (flaky, infrastructure, dependency, code, config, unknown) from the logs, and take the smallest safe step.

| | |
|---|---|
| Trigger | `workflow_run.completed` with conclusion `failure`; payload `{run_id, pr_number?}` |
| Inputs | run metadata and jobs, the tail (20 000 chars) of up to three failed jobs' logs |
| Tools (risk) | `github.get_workflow_run` (READ) · `github.get_job_logs` (READ, CONFIDENTIAL) · `github.rerun_failed_jobs` (ACT_REVERSIBLE) · `github.create_issue` (ADVISE) · `github.comment` (ADVISE); mandate also allows `github.list_commits` |
| Prompt | `ci_triage@1` |
| Output | `TriageOutput`: category, failed_jobs, root_cause, log_quotes, recommend_rerun, suggested_fix |
| Checks | `category_known` · `classification_has_quotes` (anything but `unknown` must quote log lines) · `rerun_only_when_flaky` (re-run only for `flaky` / `infrastructure`) · `rerun_at_most_once` (never on attempt ≥ 2) |
| Critic focus | a "flaky" verdict without evidence of intermittence, a re-run recommended for a code failure, root causes absent from the quotes |
| Actions | re-run failed jobs when justified **and** the mandate allows it (a denial is recorded, not fatal); open an issue for `code` / `dependency` / `config`; comment on the PR when there is one |
| Failure modes | logs unreadable → classified with what is available; re-run requested twice → rejected by `rerun_at_most_once` |
| KPIs | share of failures classified unattended, re-run success rate, false "flaky" rate |

## `iac-guardian`

**Purpose.** Turn CRITICAL/HIGH CloudGuard-IaC findings into a **draft** pull request with minimal fixes — and prove the fixes work by re-scanning.

| | |
|---|---|
| Trigger | scheduled or manual: `regent run iac-guardian --payload '{"paths": ["infra/"], "head": "regent/iac-fix", "base": "main"}'` from a job that has pushed the branch |
| Inputs | scanner findings (rule id, file, line, why, remediation), content of the flagged files (up to 8) |
| Tools (risk) | `cloudguard.scan` (READ) · `fs.read` (READ, CONFIDENTIAL) · `fs.write` (PROPOSE) · `github.create_pull_request` (PROPOSE); mandate also allows `fs.list` |
| Prompt | `iac_guardian@1` |
| Skills | `terraform-baseline` (declares the check `cloudguard_clean_after_fix`) |
| Output | `GuardianOutput`: `changes[path, content, resolves[rule ids]]`, `left_open[]` |
| Checks | `changes_only_flagged_files` · `cloudguard_clean_after_fix` — the verifier **writes the proposed files and re-runs the scanner**; the rules each change claims to resolve must be gone. In dry run the re-scan is skipped and said so. |
| Critic focus | controls weakened instead of fixed, `cloudguard:ignore` without a stated exception, hard-coded values the agent could not know, unrelated edits |
| Actions | `github.create_pull_request` with `draft: true`, body showing before/after counts |
| Failure modes | the fix does not scan clean → rejected, no PR; nothing CRITICAL/HIGH → succeeded with `pull_request: null` (only the critic ran) |
| KPIs | findings closed by draft PR, PRs merged as proposed, time from finding to merged fix |

## `incident-triage`

**Purpose.** Make the on-call engineer faster: correlate a firing alert with recent changes and metrics, rank hypotheses with evidence, propose *read-only* diagnostics, draft the status update.

| | |
|---|---|
| Trigger | Alertmanager webhook (`alert.firing`) or `--payload '{"alert": {...}, "queries": ["promql…"], "issue_number": N?}'` |
| Inputs | alert labels/annotations (**RESTRICTED** — may contain customer data), last 15 commits, up to 3 PromQL results |
| Tools (risk) | `github.list_commits` (READ) · `metrics.query` (READ) · `github.comment` (ADVISE) · `github.create_issue` (ADVISE); mandate also allows `github.compare`, `exec.kubectl.rollout.status` |
| Prompt | `incident_triage@1` |
| Skills | `incident-communication`, `kubernetes-baseline` |
| Output | `IncidentOutput`: severity (SEV1–3), `hypotheses[cause, likelihood, supporting_evidence, would_refute]`, diagnostics, recommend_rollback, rollback_target, status_update |
| Checks | `diagnostics_read_only` (allowed prefixes: `kubectl get/describe/logs/rollout status`, `curl -s`, `dig`, `promql:`, `SELECT `) · `hypotheses_have_evidence` · `severity_known` |
| Critic focus | speculation stated as fact, rollback without a matching change, diagnostics that would change state |
| Actions | comment on the incident issue or open one titled `[SEVn] <alert>`; a rollback is a **recommendation** in the text, never executed |
| Verification mode | `advisory` in the default mandate: during an incident, speed wins; the output is advice only. Issues found by the checks are logged in the ledger and shown in the record. |
| Confidentiality | the alert is `RESTRICTED`; with the default `max_remote_class: INTERNAL` the model call **routes to the local provider** or fails — see [ADR-0012](adr/ADR-0012-data-classification.md) |
| KPIs | time to first ranked hypothesis, hypothesis hit rate (post-mortem), status-update edits before publication |

## `dependency-steward`

**Purpose.** Assess bot-authored dependency bumps; merge the routine ones under policy; send the rest to a human with the changelog quoted.

| | |
|---|---|
| Trigger | `pull_request` opened by `dependabot[bot]` / `renovate[bot]`; payload `{number, ci_green}` |
| Inputs | PR metadata, diff (30 000 chars), CI status |
| Tools (risk) | `github.get_pr` (READ) · `github.get_pr_diff` (READ) · `github.merge_pull_request` (ACT_REVERSIBLE) · `github.add_labels` (ADVISE) · `github.comment` (ADVISE); mandate also allows `github.list_pr_files`, `github.get_workflow_run` |
| Prompt | `dependency_steward@1` |
| Skills | `dependency-policy`, `conventional-commits` |
| Output | `StewardOutput`: package, from/to version, bump (patch/minor/major, recomputed in code), decision (`routine` / `review`), changelog_quotes, security_fix |
| Checks (only when decision = routine) | `author_is_bot` · `ci_green` · `bump_is_patch_or_minor` · `no_breaking_note` (changelog quotes must not mention break/deprecat/migrat) |
| Actions | `routine`: merge (squash) — **requires approval in the default mandate**, so the run ends `awaiting_approval` with labels `regent:routine`, `needs-approval`; a repository override (`policies/mandates/overrides.example.yaml`, scope `acme/internal-tools`) lifts it. `review`: label `regent:review`. Always a comment. |
| KPIs | bot PRs merged unattended, reverts of steward merges (must be ~0), median age of open bot PRs |

## `release-scribe`

**Purpose.** Release notes from the commits between two refs, grouped by conventional-commit type, published as a **draft** release.

| | |
|---|---|
| Trigger | `release.created` webhook or `--payload '{"base": "v1.0.0", "head": "v1.1.0"}'` |
| Tools (risk) | `github.compare` (READ) · `github.create_release` (PROPOSE, `draft: true`); mandate also allows `github.list_commits` |
| Prompt | `release_scribe@1` |
| Skills | `conventional-commits` |
| Output | `NotesOutput`: version, breaking, features, fixes, security, other |
| Checks | `notes_not_longer_than_history` (cannot describe more changes than there were commits) |
| Verification mode | `advisory` — a draft release is harmless and a human publishes it |
| KPIs | edits before publication |

---

## The verifier

Not an agent you trigger: `verify()` runs inside every run between analyse and act.

1. Runs the agent's **deterministic checks**. Any failure is an issue.
2. Builds a critique request: the agent's description and `verification_focus()`, the check results, a digest of tool calls, the proposed output and its evidence — both wrapped as `<untrusted_data>`.
3. Calls prompt `verifier@1` on a tier **never cheaper** than the author's (`fast` → `balanced`), effort `high`, asking for `{accept, issues, confidence}`.
4. Verdict: accepted only if the critic accepts **and** no check failed. The verdict is written to the ledger (`verification`) and counted in `regent_verifications_total`.

Mandate field `verification`: `required` (rejection stops the run before act), `advisory` (issues logged, run continues), `none` (skipped; the ledger records `skipped: true`).

The critic is separation of duties applied to models: a different prompt, an explicit instruction to never fix or rewrite, and the author's claims presented as data.

## How to add an agent

1. Create `regent/agents/my_agent.py`:

```python
from typing import Any, ClassVar
from pydantic import Field
from regent.agents.base import Agent, AgentOutput, CheckResult, expect
from regent.core.models import DataClass, RiskClass
from regent.runtime.context import RunContext


class MyOutput(AgentOutput):
    items: list[str] = Field(default_factory=list)


class MyAgent(Agent):
    name: ClassVar[str] = "my-agent"
    description: ClassVar[str] = "What it does, in one line"
    default_tier: ClassVar[str] = "balanced"
    default_skills: ClassVar[tuple[str, ...]] = ()
    highest_risk: ClassVar[RiskClass] = RiskClass.ADVISE
    output_type: ClassVar[type[AgentOutput]] = MyOutput

    def analyse(self, ctx: RunContext) -> AgentOutput:
        data = ctx.tool("github.get_pr", number=int(ctx.trigger.payload["number"]))
        completion = ctx.llm(
            "my_agent",
            values={"repository": ctx.repository},
            user=ctx.untrusted("pr", str(data.output), DataClass.INTERNAL),
            schema=self.output_schema(),
        )
        return MyOutput.model_validate(completion.parsed)

    def checks(self, output: AgentOutput, ctx: RunContext) -> list[CheckResult]:
        output = expect(output, MyOutput)
        return [CheckResult(check="has_items", passed=bool(output.items))]

    def act(self, output: AgentOutput, ctx: RunContext) -> dict[str, Any]:
        output = expect(output, MyOutput)
        return {
            "comment": ctx.tool("github.comment", number=1, body="\n".join(output.items)).output
        }
```

2. Add the prompt `regent/prompts/my_agent.md` with front-matter `version: "1"` and the sentence about `<untrusted_data>` being data.
3. Register the class in `DEFAULT_AGENTS` (`regent/bootstrap.py`).
4. Add a mandate in `policies/mandates/defaults.yaml` — `regent policy-check` fails until every agent has one and every tool it names exists.
5. Add tests under `tests/` using the `runner` fixture (scripted model answers, fake GitHub) and an eval case under `evals/cases/`.

The [runbook](runbooks/add-an-agent.md) has the checklist.
