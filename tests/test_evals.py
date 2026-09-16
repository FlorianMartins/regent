from pathlib import Path

from regent.evals.runner import run_case, run_suite


def test_shipped_eval_suite_passes():
    results = run_suite(Path("evals/cases"))
    assert results, "no eval cases found"
    failed = [r for r in results if not r.passed]
    assert not failed, "\n".join(f"{r.case}: {r.detail}" for r in failed)


def test_eval_failure_is_reported(tmp_path: Path):
    case = tmp_path / "bad.yaml"
    case.write_text(
        "agent: release-scribe\npayload: {base: a, head: b}\n"
        "world: {github: {'json /repos/*/compare/*': {ahead_by: 0, commits: []}}}\n"
        "model: {}\nexpect: {status: succeeded}\n"
    )
    r = run_case(case)
    assert not r.passed and "status failed" in r.detail
