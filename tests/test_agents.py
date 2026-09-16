from pathlib import Path

from regent.core.models import RunStatus
from regent.core.policy import MandateStore
from tests.conftest import ACCEPT, SAMPLE_PR

RUN = {
    "id": 777,
    "name": "CI",
    "status": "completed",
    "conclusion": "failure",
    "head_sha": "abc",
    "head_branch": "feat/x",
    "run_attempt": 1,
    "event": "pull_request",
}
JOBS = {
    "jobs": [
        {
            "id": 1,
            "name": "test",
            "conclusion": "failure",
            "steps": [{"name": "pytest", "conclusion": "failure"}],
        }
    ]
}
LOG = "collecting...\nE   ConnectionResetError: connection reset by peer while pulling image\n"


def ci_world():
    return {
        "json /repos/*/actions/runs/777": RUN,
        "json /repos/*/actions/runs/777/jobs": JOBS,
        "plain /repos/*/actions/jobs/1/logs": LOG,
        "json /repos/*/actions/jobs/1/logs": LOG,
    }


def triage(category: str, rerun: bool, quotes=("ConnectionResetError: connection reset by peer",)):
    return {
        "json": {
            "summary": f"{category} failure",
            "confidence": 0.8,
            "evidence": list(quotes),
            "category": category,
            "failed_jobs": [],
            "root_cause": "registry hiccup",
            "log_quotes": list(quotes),
            "recommend_rerun": rerun,
            "suggested_fix": "",
        }
    }


def test_ci_triage_reruns_flaky_job(runner):
    record, github, _ = runner(
        "ci-triage",
        model={"ci_triage@1": [triage("infrastructure", True)], "verifier@1": [ACCEPT]},
        world=ci_world(),
        run_id=777,
        pr_number=42,
    )
    assert record.status is RunStatus.SUCCEEDED, record.error
    paths = [w["path"] for w in github.writes]
    assert any(p.endswith("/rerun-failed-jobs") for p in paths)
    assert any(p.endswith("/issues/42/comments") for p in paths)
    assert record.output["actions"]["rerun"]["rerun"] is True


def test_ci_triage_code_failure_opens_issue_and_never_reruns(runner):
    record, github, _ = runner(
        "ci-triage",
        model={"ci_triage@1": [triage("code", False)], "verifier@1": [ACCEPT]},
        world=ci_world(),
        run_id=777,
    )
    assert record.status is RunStatus.SUCCEEDED
    paths = [w["path"] for w in github.writes]
    assert any(p.endswith("/issues") for p in paths) and not any("rerun" in p for p in paths)


def test_ci_triage_rejects_rerun_for_code_failure(runner):
    record, github, _ = runner(
        "ci-triage",
        model={"ci_triage@1": [triage("code", True)], "verifier@1": [ACCEPT]},
        world=ci_world(),
        run_id=777,
    )
    assert (
        record.status is RunStatus.FAILED
        and "rerun_only_when_flaky" in record.error
        and github.writes == []
    )


def test_ci_triage_rerun_at_most_once(runner):
    world = ci_world()
    world["json /repos/*/actions/runs/777"] = {**RUN, "run_attempt": 2}
    record, _, _ = runner(
        "ci-triage",
        model={"ci_triage@1": [triage("flaky", True)], "verifier@1": [ACCEPT]},
        world=world,
        run_id=777,
    )
    assert record.status is RunStatus.FAILED and "rerun_at_most_once" in record.error


def test_ci_triage_needs_quotes(runner):
    record, _, _ = runner(
        "ci-triage",
        model={"ci_triage@1": [triage("code", False, quotes=())], "verifier@1": [ACCEPT]},
        world=ci_world(),
        run_id=777,
    )
    assert record.status is RunStatus.FAILED and "classification_has_quotes" in record.error


# --- IaC guardian: real CloudGuard scan, real re-scan -------------------------

VULNERABLE_TF = """resource "aws_s3_bucket" "logs" {
  bucket = "acme-logs"
  acl    = "public-read"
}
"""
FIXED_TF = """resource "aws_s3_bucket" "logs" {
  bucket = "acme-logs"
}

resource "aws_s3_bucket_public_access_block" "logs" {
  bucket                  = aws_s3_bucket.logs.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "logs" {
  bucket = aws_s3_bucket.logs.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = var.kms_key_arn
    }
  }
}

resource "aws_s3_bucket_versioning" "logs" {
  bucket = aws_s3_bucket.logs.id
  versioning_configuration {
    status = "Enabled"
  }
}
"""


def guardian_answer(content: str, resolves=("CG_IAC_001",)):
    return {
        "json": {
            "summary": "Made the bucket private.",
            "confidence": 0.9,
            "evidence": ["CG_IAC_001 main.tf"],
            "changes": [{"path": "main.tf", "content": content, "resolves": list(resolves)}],
            "left_open": [],
        }
    }


def test_iac_guardian_fixes_and_rescans(runner, tmp_path: Path):
    (tmp_path / "main.tf").write_text(VULNERABLE_TF)
    record, github, _ = runner(
        "iac-guardian",
        model={"iac_guardian@1": [guardian_answer(FIXED_TF)], "verifier@1": [ACCEPT]},
        workspace=tmp_path,
        paths=["main.tf"],
        head="regent/fix",
        base="main",
    )
    assert record.status is RunStatus.SUCCEEDED, record.error
    assert (tmp_path / "main.tf").read_text() == FIXED_TF
    assert any(w["path"].endswith("/pulls") and w["json"]["draft"] for w in github.writes)
    checks = {c["check"]: c["passed"] for c in record.output["verdict"]["checks"]}
    assert checks["cloudguard_clean_after_fix"] and checks["changes_only_flagged_files"]


def test_iac_guardian_rejects_fix_that_does_not_scan_clean(runner, tmp_path: Path):
    (tmp_path / "main.tf").write_text(VULNERABLE_TF)
    record, github, _ = runner(
        "iac-guardian",
        model={"iac_guardian@1": [guardian_answer(VULNERABLE_TF)], "verifier@1": [ACCEPT]},
        workspace=tmp_path,
        paths=["main.tf"],
    )
    assert record.status is RunStatus.FAILED and "cloudguard_clean_after_fix" in record.error
    assert github.writes == []


def test_iac_guardian_rejects_stray_file(runner, tmp_path: Path):
    (tmp_path / "main.tf").write_text(VULNERABLE_TF)
    answer = {
        "json": {
            **guardian_answer(FIXED_TF)["json"],
            "changes": [{"path": "other.tf", "content": "x", "resolves": []}],
        }
    }
    record, _, _ = runner(
        "iac-guardian",
        model={"iac_guardian@1": [answer], "verifier@1": [ACCEPT]},
        workspace=tmp_path,
        paths=["main.tf"],
    )
    assert record.status is RunStatus.FAILED and "changes_only_flagged_files" in record.error


def test_iac_guardian_nothing_to_fix(runner, tmp_path: Path):
    (tmp_path / "main.tf").write_text('variable "x" {}\n')
    record, _github, replay = runner(
        "iac-guardian", model={"verifier@1": [ACCEPT]}, workspace=tmp_path, paths=["main.tf"]
    )
    assert record.status is RunStatus.SUCCEEDED and record.output["actions"]["pull_request"] is None
    assert len(replay.requests) == 1  # only the critic ran


def test_iac_guardian_dry_run_skips_rescan(runner, tmp_path: Path):
    (tmp_path / "main.tf").write_text(VULNERABLE_TF)
    record, _, _ = runner(
        "iac-guardian",
        model={"iac_guardian@1": [guardian_answer(FIXED_TF)], "verifier@1": [ACCEPT]},
        workspace=tmp_path,
        dry_run=True,
        paths=["main.tf"],
    )
    assert (
        record.status is RunStatus.SUCCEEDED and (tmp_path / "main.tf").read_text() == VULNERABLE_TF
    )


# --- incident triage -----------------------------------------------------------

COMMITS = [
    {"sha": "a" * 40, "commit": {"message": "feat: raise pool size", "author": {"name": "bob"}}}
]


def incident(diagnostics, hyp_evidence=("error rate rose at 10:02, deploy at 10:00",)):
    return {
        "json": {
            "summary": "Likely the pool change.",
            "confidence": 0.7,
            "evidence": list(hyp_evidence),
            "severity": "SEV2",
            "hypotheses": [
                {
                    "cause": "pool size change",
                    "likelihood": 0.7,
                    "supporting_evidence": list(hyp_evidence),
                    "would_refute": "errors persist after rollback",
                }
            ],
            "diagnostics": diagnostics,
            "recommend_rollback": True,
            "rollback_target": "v1.2.3",
            "status_update": "We are investigating elevated errors.",
        }
    }


def test_incident_triage_opens_issue(runner):
    world = {"json /repos/*/commits": COMMITS}
    record, github, _ = runner(
        "incident-triage",
        model={
            "incident_triage@1": [incident(["kubectl get pods -n api"])],
            "verifier@1": [ACCEPT],
        },
        world=world,
        environment="prod",
        alert={"name": "HighErrorRate", "severity": "page"},
    )
    assert record.status is RunStatus.SUCCEEDED, record.error
    issue = next(w for w in github.writes if w["path"].endswith("/issues"))
    assert (
        issue["json"]["title"].startswith("[SEV2]")
        and "Rollback recommended" in issue["json"]["body"]
    )


def test_incident_triage_is_advisory_so_unsafe_diagnostics_are_logged_not_blocking(runner):
    world = {"json /repos/*/commits": COMMITS}
    record, _github, _ = runner(
        "incident-triage",
        model={"incident_triage@1": [incident(["kubectl delete pod x"])], "verifier@1": [ACCEPT]},
        world=world,
        environment="prod",
        alert={"name": "X"},
        issue_number=9,
    )
    assert record.status is RunStatus.SUCCEEDED  # verification is advisory for this agent
    assert record.output["verdict"]["accepted"] is False
    assert any("diagnostics_read_only" in i for i in record.output["verdict"]["issues"])


def test_incident_triage_required_verification_blocks(runner, mandates):
    m = mandates.resolve("incident-triage", "acme/example", "prod").model_copy(
        update={"verification": "required"}
    )
    world = {"json /repos/*/commits": COMMITS}
    record, github, _ = runner(
        "incident-triage",
        model={"incident_triage@1": [incident(["kubectl delete pod x"])], "verifier@1": [ACCEPT]},
        world=world,
        store=MandateStore([m]),
        environment="prod",
        alert={"name": "X"},
    )
    assert record.status is RunStatus.FAILED and github.writes == []


# --- dependency steward -------------------------------------------------------

BOT_PR = {
    **SAMPLE_PR,
    "user": {"login": "dependabot[bot]"},
    "title": "build(deps): bump httpx from 0.27.0 to 0.27.2",
}


def steward(decision: str, quotes=("Fix a regression in timeouts",), frm="0.27.0", to="0.27.2"):
    return {
        "json": {
            "summary": "Patch release.",
            "confidence": 0.9,
            "evidence": list(quotes),
            "package": "httpx",
            "from_version": frm,
            "to_version": to,
            "bump": "patch",
            "decision": decision,
            "changelog_quotes": list(quotes),
            "security_fix": False,
        }
    }


def test_steward_routine_needs_approval_by_default(runner):
    world = {
        "json /repos/*/pulls/42": BOT_PR,
        "diff /repos/*/pulls/42": "-httpx==0.27.0\n+httpx==0.27.2\n",
    }
    record, github, _ = runner(
        "dependency-steward",
        model={"dependency_steward@1": [steward("routine")], "verifier@1": [ACCEPT]},
        world=world,
        number=42,
        ci_green=True,
    )
    assert (
        record.status is RunStatus.AWAITING_APPROVAL
        and record.pending_call.tool == "github.merge_pull_request"
    )
    assert any(
        w["path"].endswith("/labels") and "needs-approval" in w["json"]["labels"]
        for w in github.writes
    )


def test_steward_merges_on_low_risk_repo_override(runner):
    world = {
        "json /repos/*/pulls/42": BOT_PR,
        "diff /repos/*/pulls/42": "-httpx==0.27.0\n+httpx==0.27.2\n",
    }
    record, _github, _ = runner(
        "dependency-steward",
        model={"dependency_steward@1": [steward("routine")], "verifier@1": [ACCEPT]},
        world=world,
        repository="acme/internal-tools",
        number=42,
        ci_green=True,
    )
    assert record.status is RunStatus.SUCCEEDED, record.error
    assert record.output["actions"]["merge"]["merged"] is True


def test_steward_routine_rejected_when_ci_red(runner):
    world = {"json /repos/*/pulls/42": BOT_PR, "diff /repos/*/pulls/42": "x"}
    record, github, _ = runner(
        "dependency-steward",
        model={"dependency_steward@1": [steward("routine")], "verifier@1": [ACCEPT]},
        world=world,
        repository="acme/internal-tools",
        number=42,
        ci_green=False,
    )
    assert record.status is RunStatus.FAILED and "ci_green" in record.error and github.writes == []


def test_steward_major_bump_goes_to_review(runner):
    world = {"json /repos/*/pulls/42": BOT_PR, "diff /repos/*/pulls/42": "x"}
    record, github, _ = runner(
        "dependency-steward",
        model={
            "dependency_steward@1": [steward("review", frm="1.9.0", to="2.0.0")],
            "verifier@1": [ACCEPT],
        },
        world=world,
        number=42,
        ci_green=True,
    )
    assert record.status is RunStatus.SUCCEEDED and record.output["actions"]["bump"] == "major"
    assert any("regent:review" in (w["json"] or {}).get("labels", []) for w in github.writes)


def test_steward_rejects_routine_from_human_author(runner):
    world = {"json /repos/*/pulls/42": SAMPLE_PR, "diff /repos/*/pulls/42": "x"}
    record, _, _ = runner(
        "dependency-steward",
        model={"dependency_steward@1": [steward("routine")], "verifier@1": [ACCEPT]},
        world=world,
        repository="acme/internal-tools",
        number=42,
        ci_green=True,
    )
    assert record.status is RunStatus.FAILED and "author_is_bot" in record.error


def test_classify_bump():
    from regent.agents.dependency_steward import classify_bump

    assert classify_bump("1.2.3", "1.2.4") == "patch"
    assert classify_bump("v1.2.3", "v1.3.0") == "minor"
    assert classify_bump("1.2.3", "2.0.0") == "major"
    assert classify_bump("", "1.0") is None


# --- release scribe ------------------------------------------------------------

COMPARE = {
    "ahead_by": 2,
    "commits": [
        {"sha": "a" * 40, "commit": {"message": "feat(api): add /runs"}},
        {"sha": "b" * 40, "commit": {"message": "fix!: drop legacy flag"}},
    ],
}


def notes(n_lines: int):
    return {
        "json": {
            "summary": "Two changes.",
            "confidence": 0.9,
            "evidence": [],
            "version": "v1.1.0",
            "breaking": ["drop legacy flag"] if n_lines else [],
            "features": ["add /runs"] if n_lines else [],
            "fixes": [],
            "security": [],
            "other": ["x"] * max(0, n_lines - 2),
        }
    }


def test_release_scribe_drafts_release(runner):
    record, github, _ = runner(
        "release-scribe",
        model={"release_scribe@1": [notes(2)], "verifier@1": [ACCEPT]},
        world={"json /repos/*/compare/*": COMPARE},
        base="v1.0.0",
        head="v1.1.0",
    )
    assert record.status is RunStatus.SUCCEEDED, record.error
    rel = next(w for w in github.writes if w["path"].endswith("/releases"))
    assert rel["json"]["draft"] is True and "Breaking changes" in rel["json"]["body"]


def test_release_scribe_cannot_invent_changes(runner):
    record, _github, _ = runner(
        "release-scribe",
        model={"release_scribe@1": [notes(5)], "verifier@1": [ACCEPT]},
        world={"json /repos/*/compare/*": COMPARE},
        base="v1.0.0",
        head="v1.1.0",
    )
    # verification is advisory for release-scribe: the release is still drafted, the issue is logged
    assert record.status is RunStatus.SUCCEEDED and record.output["verdict"]["accepted"] is False


def test_agent_highest_risk_matches_mandates(mandates):
    from regent.bootstrap import DEFAULT_AGENTS

    for cls in DEFAULT_AGENTS:
        m = mandates.resolve(cls.name, "acme/example", "dev")
        assert int(cls.highest_risk) <= int(m.autonomy), cls.name


def test_output_schema_is_strict():
    from regent.agents.pr_reviewer import PRReviewer

    schema = PRReviewer().output_schema()
    assert schema["additionalProperties"] is False and "findings" in schema["required"]
    finding = schema["$defs"]["Finding"]
    assert (
        finding["additionalProperties"] is False and "default" not in finding["properties"]["quote"]
    )
