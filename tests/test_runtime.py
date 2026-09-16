from pathlib import Path

import pytest

from regent.core.ledger import Ledger
from regent.core.models import Autonomy, Budget, Mandate, RunStatus
from regent.core.policy import MandateStore
from tests.conftest import ACCEPT, REJECT

REVIEW = {
    "json": {
        "summary": "One SQL injection.",
        "confidence": 0.9,
        "evidence": ["app/db.py:4 string concatenation into SQL"],
        "findings": [
            {
                "file": "app/db.py",
                "line": 4,
                "severity": "critical",
                "category": "security",
                "title": "SQL injection",
                "detail": "user is concatenated into the query",
                "quote": 'query = "SELECT ..." + user',
                "suggestion": "",
            }
        ],
        "diff_truncated": False,
    }
}


def test_happy_path_posts_review_and_ledger_is_intact(runner, tmp_path):
    record, github, replay = runner(
        "pr-reviewer", model={"pr_reviewer@1": [REVIEW], "verifier@1": [ACCEPT]}, number=42
    )
    assert record.status is RunStatus.SUCCEEDED, record.error
    assert record.output["actions"]["findings"] == 1
    writes = [w["path"] for w in github.writes]
    assert any(p.endswith("/pulls/42/reviews") for p in writes)
    assert any(p.endswith("/labels") for p in writes)
    assert record.usage.llm_calls == 2 and record.usage.tool_calls == 4
    # the critic saw the proposed output as untrusted data
    assert "<untrusted_data" in replay.requests[1].messages[0].content
    # skills were composed into the reviewer's system prompt
    assert "secure-review" in replay.requests[0].system


def test_verification_rejection_blocks_action(runner):
    record, github, _ = runner(
        "pr-reviewer", model={"pr_reviewer@1": [REVIEW], "verifier@1": [REJECT]}, number=42
    )
    assert record.status is RunStatus.FAILED and "verification rejected" in record.error
    assert github.writes == []


def test_deterministic_check_failure_rejects_even_if_critic_accepts(runner):
    bad = {
        "json": {
            **REVIEW["json"],
            "findings": [{**REVIEW["json"]["findings"][0], "file": "not/in/diff.py"}],
        }
    }
    record, github, _ = runner(
        "pr-reviewer", model={"pr_reviewer@1": [bad], "verifier@1": [ACCEPT]}, number=42
    )
    assert record.status is RunStatus.FAILED and "findings_cite_lines" in record.error
    assert github.writes == []


def test_no_mandate_means_denied(runner):
    store = MandateStore([])
    record, github, _ = runner("pr-reviewer", model={}, store=store, number=42)
    assert record.status is RunStatus.DENIED and github.writes == [] and record.usage.llm_calls == 0


def test_kill_switch(runner, mandates):
    store = MandateStore([*mandates.all(), Mandate(agent="pr-reviewer", kill_switch=True)])
    record, _, _ = runner("pr-reviewer", model={}, store=store, number=42)
    assert record.status is RunStatus.DENIED and "kill switch" in record.error


def test_tool_outside_allow_list_is_denied(runner):
    store = MandateStore(
        [
            Mandate(
                agent="pr-reviewer", autonomy=Autonomy.L1_ADVISE, allowed_tools=("github.get_pr",)
            )
        ]
    )
    record, _, _ = runner("pr-reviewer", model={}, store=store, number=42)
    assert record.status is RunStatus.DENIED and record.pending_call.tool == "github.get_pr_diff"


def test_phase_gate_blocks_writes_during_analysis(make_platform, trigger):
    from regent.agents.base import Agent, AgentOutput
    from regent.runtime.runner import Runner

    class Sneaky(Agent):
        name = "sneaky"
        description = "writes during analysis"

        def analyse(self, ctx):
            ctx.tool("github.comment", number=42, body="hi")
            return AgentOutput(summary="x")

        def act(self, _output, _ctx):
            return {}

    store = MandateStore(
        [Mandate(agent="sneaky", autonomy=Autonomy.L1_ADVISE, allowed_tools=("github.*",))]
    )
    platform, _, github = make_platform(store=store)
    platform.register(Sneaky())
    record = Runner(platform).run("sneaky", repository="acme/x", trigger=trigger(number=42))
    assert (
        record.status is RunStatus.DENIED and "phase gate" in record.error and github.writes == []
    )


def test_approval_required_then_granted(runner):
    store = MandateStore(
        [
            Mandate(
                agent="pr-reviewer",
                autonomy=Autonomy.L1_ADVISE,
                allowed_tools=("github.*",),
                requires_approval=("github.create_review",),
            )
        ]
    )
    record, github, _ = runner(
        "pr-reviewer",
        model={"pr_reviewer@1": [REVIEW], "verifier@1": [ACCEPT]},
        store=store,
        number=42,
    )
    assert (
        record.status is RunStatus.AWAITING_APPROVAL
        and record.pending_call.tool == "github.create_review"
    )
    assert github.writes == []
    record, github, _ = runner(
        "pr-reviewer",
        model={"pr_reviewer@1": [REVIEW], "verifier@1": [ACCEPT]},
        store=store,
        approvals=("github.create_review",),
        number=42,
    )
    assert record.status is RunStatus.SUCCEEDED and len(github.writes) == 2


def test_budget_exceeded(runner):
    store = MandateStore(
        [
            Mandate(
                agent="pr-reviewer",
                autonomy=Autonomy.L1_ADVISE,
                allowed_tools=("github.*",),
                budget=Budget(max_llm_calls=1),
            )
        ]
    )
    record, _, _ = runner(
        "pr-reviewer",
        model={"pr_reviewer@1": [REVIEW], "verifier@1": [ACCEPT]},
        store=store,
        number=42,
    )
    assert record.status is RunStatus.BUDGET_EXCEEDED and "llm_calls" in record.error


def test_dry_run_performs_no_write(runner):
    record, github, _ = runner(
        "pr-reviewer",
        model={"pr_reviewer@1": [REVIEW], "verifier@1": [ACCEPT]},
        dry_run=True,
        number=42,
    )
    assert record.status is RunStatus.SUCCEEDED
    assert github.writes == [] and record.output["actions"]["review"]["dry_run"] is True


def test_provider_error_fails_cleanly(runner):
    record, _, _ = runner("pr-reviewer", model={}, number=42)
    assert record.status is RunStatus.FAILED and "ProviderError" in record.error


def test_verification_none_skips_critic(runner, mandates):
    m = mandates.resolve("pr-reviewer", "acme/example", "dev").model_copy(
        update={"verification": "none"}
    )
    store = MandateStore([m])
    record, _, replay = runner(
        "pr-reviewer", model={"pr_reviewer@1": [REVIEW]}, store=store, number=42
    )
    assert record.status is RunStatus.SUCCEEDED and record.output["verdict"]["skipped"] is True
    assert len(replay.requests) == 1


def test_unknown_agent(make_platform, trigger):
    from regent.runtime.runner import Runner

    platform, _, _ = make_platform()
    with pytest.raises(KeyError, match="unknown agent"):
        Runner(platform).run("nope", repository="a/b", trigger=trigger())


def test_ledger_records_every_step(make_platform, trigger, tmp_path: Path):
    from regent.runtime.runner import Runner

    path = tmp_path / "audit.jsonl"
    platform, _, _ = make_platform(
        model={"pr_reviewer@1": [REVIEW], "verifier@1": [ACCEPT]}, ledger_path=path
    )
    record = Runner(platform).run("pr-reviewer", repository="acme/x", trigger=trigger(number=42))
    kinds = [e.kind for e in platform.ledger.events(record.run_id)]
    assert kinds[0] == "run.started" and kinds[-1] == "run.finished"
    assert kinds.count("llm.call") == 2 and "verification" in kinds and "analysis" in kinds
    assert kinds.count("tool.decision") == kinds.count("tool.call") == 4
    assert Ledger.verify(path) == len(kinds)
    started = platform.ledger.events(record.run_id)[0].data
    assert started["skills"] and started["mandate"]["autonomy"] == "L1_ADVISE"
