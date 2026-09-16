import json
from pathlib import Path

from typer.testing import CliRunner

from regent import __version__
from regent.cli.main import app

cli = CliRunner(env={"COLUMNS": "250", "TERM": "dumb", "FORCE_COLOR": None, "NO_COLOR": "1"})


def test_version():
    r = cli.invoke(app, ["--version"])
    assert r.exit_code == 0 and __version__ in r.output


def test_agents_and_skills_tables():
    assert "pr-reviewer" in cli.invoke(app, ["agents"]).output
    assert "secure-review" in cli.invoke(app, ["skills"]).output


def test_mandates_listing_and_resolution():
    r = cli.invoke(app, ["mandates"])
    assert r.exit_code == 0 and "iac-guardian" in r.output
    r = cli.invoke(app, ["mandates", "--agent", "pr-reviewer"])
    assert r.exit_code == 0 and "L1_ADVISE" in r.output
    r = cli.invoke(app, ["mandates", "--agent", "nope"])
    assert r.exit_code == 1


def test_policy_check_passes_on_shipped_policies():
    r = cli.invoke(app, ["policy-check"])
    assert r.exit_code == 0, r.output


def test_policy_check_catches_violations(tmp_path: Path):
    (tmp_path / "m.yaml").write_text(
        "- agent: pr-reviewer\n  autonomy: L4_ACT\n  allowed_tools: ['*']\n  budget: {max_usd: 50}\n"
        "- agent: ghost\n  allowed_tools: ['github.nope']\n"
    )
    r = cli.invoke(app, ["policy-check", "--dir", str(tmp_path)])
    assert r.exit_code == 1
    for needle in (
        "L4_ACT",
        "wildcard",
        "20 USD",
        "unknown agent",
        "unknown tool",
        "no mandate at all",
    ):
        assert needle in r.output, needle


def test_ledger_verify_and_show(tmp_path: Path):
    from regent.core.ledger import Ledger

    path = tmp_path / "l.jsonl"
    Ledger(path).append("run1", "run.started", {"a": 1})
    assert cli.invoke(app, ["ledger", "verify", str(path)]).exit_code == 0
    assert "run.started" in cli.invoke(app, ["ledger", "show", str(path)]).output
    path.write_text(path.read_text().replace('"a":1', '"a":2').replace('"a": 1', '"a": 2'))
    assert cli.invoke(app, ["ledger", "verify", str(path)]).exit_code == 1
    assert cli.invoke(app, ["ledger", "verify", str(tmp_path / "missing")]).exit_code == 1


def test_run_with_replay_provider(tmp_path: Path, monkeypatch):
    fixture = tmp_path / "fx.json"
    fixture.write_text(
        json.dumps(
            {
                "by_prompt": {
                    "release_scribe@1": [
                        {
                            "json": {
                                "summary": "s",
                                "confidence": 0.9,
                                "evidence": [],
                                "version": "v1",
                                "breaking": [],
                                "features": [],
                                "fixes": [],
                                "security": [],
                                "other": [],
                            }
                        }
                    ],
                    "verifier@1": [{"json": {"accept": True, "issues": [], "confidence": 0.9}}],
                }
            }
        )
    )
    monkeypatch.setenv("REGENT_REPLAY_FILE", str(fixture))
    monkeypatch.setenv("REGENT_LEDGER", str(tmp_path / "ledger.jsonl"))
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    out = tmp_path / "record.json"
    # dry run: the compare call would need the network, so this run fails at the first tool
    r = cli.invoke(
        app,
        [
            "run",
            "release-scribe",
            "--repo",
            "acme/x",
            "--provider",
            "replay",
            "--dry-run",
            "-p",
            '{"base":"a","head":"b"}',
            "-o",
            str(out),
        ],
    )
    assert r.exit_code == 1 and "status" in r.output
    record = json.loads(out.read_text())
    assert record["status"] in ("failed", "denied")
    assert cli.invoke(app, ["ledger", "verify", str(tmp_path / "ledger.jsonl")]).exit_code == 0


def test_run_rejects_bad_config(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    r = cli.invoke(app, ["run", "pr-reviewer", "--repo", "a/b", "--provider", "anthropic"])
    assert r.exit_code == 2 and "ANTHROPIC_API_KEY" in r.output
    r = cli.invoke(app, ["run", "nope", "--repo", "a/b", "--provider", "replay"])
    assert r.exit_code == 2


def test_evals_command(tmp_path: Path):
    r = cli.invoke(app, ["evals", "--report", str(tmp_path / "reports" / "r.json")])
    assert r.exit_code == 0 and "passed" in r.output and (tmp_path / "reports" / "r.json").exists()
