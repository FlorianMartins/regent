from pathlib import Path

import pytest

from regent.core.models import Autonomy, DataClass, DecisionKind, Mandate, RiskClass
from regent.core.policy import MandateStore, PolicyError, evaluate


def mandate(**kw):
    base = {"agent": "a", "allowed_tools": ("github.*", "fs.read"), "autonomy": Autonomy.L2_PROPOSE}
    base.update(kw)
    return Mandate(**base)


def test_allow_within_mandate():
    d = evaluate(mandate(), "github.comment", RiskClass.ADVISE)
    assert d.kind is DecisionKind.ALLOW and d.rule == "allow"


def test_kill_switch_denies_everything():
    d = evaluate(mandate(kill_switch=True), "fs.read", RiskClass.READ)
    assert d.kind is DecisionKind.DENY and d.rule == "kill_switch"


def test_denied_pattern_wins_over_allowed():
    d = evaluate(
        mandate(denied_tools=("github.merge_*",)),
        "github.merge_pull_request",
        RiskClass.ACT_REVERSIBLE,
    )
    assert d.rule == "denied"


def test_not_in_allow_list_is_denied():
    d = evaluate(mandate(), "exec.pytest", RiskClass.READ)
    assert d.rule == "not_allowed"


def test_destructive_is_never_allowed_without_l4():
    d = evaluate(
        mandate(autonomy=Autonomy.L3_ACT_REVERSIBLE), "github.comment", RiskClass.DESTRUCTIVE
    )
    assert d.rule == "destructive"


def test_risk_above_autonomy_is_denied():
    d = evaluate(
        mandate(autonomy=Autonomy.L1_ADVISE), "github.create_pull_request", RiskClass.PROPOSE
    )
    assert d.rule == "autonomy" and "L2_PROPOSE" in d.reason


def test_requires_approval():
    d = evaluate(
        mandate(requires_approval=("github.create_*",)),
        "github.create_pull_request",
        RiskClass.PROPOSE,
    )
    assert d.kind is DecisionKind.REQUIRE_APPROVAL


def test_resolve_prefers_specific_scope():
    store = MandateStore(
        [
            mandate(scopes=("*",), autonomy=Autonomy.L1_ADVISE),
            mandate(scopes=("acme/*",), autonomy=Autonomy.L2_PROPOSE),
            mandate(scopes=("acme/core",), environments=("prod",), autonomy=Autonomy.L0_OBSERVE),
        ]
    )
    assert store.resolve("a", "other/repo", "dev").autonomy is Autonomy.L1_ADVISE
    assert store.resolve("a", "acme/tools", "dev").autonomy is Autonomy.L2_PROPOSE
    assert store.resolve("a", "acme/core", "prod").autonomy is Autonomy.L0_OBSERVE
    assert store.resolve("a", "acme/core", "dev").autonomy is Autonomy.L2_PROPOSE
    assert store.resolve("b", "acme/core", "dev") is None


def test_resolve_last_loaded_wins_on_tie():
    store = MandateStore([mandate(model_tier="fast"), mandate(model_tier="deep")])
    assert store.resolve("a", "x/y", "dev").model_tier == "deep"


def test_kill_switch_anywhere_wins():
    store = MandateStore([mandate(kill_switch=True), mandate(scopes=("acme/*",))])
    assert store.resolve("a", "acme/core", "dev").kill_switch is True


def test_shipped_mandates_load_and_cover_every_agent():
    from regent.bootstrap import DEFAULT_AGENTS

    store = MandateStore.from_directory(Path("policies/mandates"))
    for cls in DEFAULT_AGENTS:
        m = store.resolve(cls.name, "acme/example", "dev")
        assert m is not None, cls.name
        assert m.autonomy < Autonomy.L4_ACT
        assert "*" not in m.allowed_tools


def test_override_example_is_more_specific():
    store = MandateStore.from_directory(Path("policies/mandates"))
    m = store.resolve("dependency-steward", "acme/internal-tools", "dev")
    assert m.requires_approval == ()
    m = store.resolve("incident-triage", "acme/payments-api", "prod")
    assert m.max_remote_class is DataClass.PUBLIC


def test_parse_errors(tmp_path: Path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("- autonomy: L1_ADVISE\n")
    with pytest.raises(PolicyError, match="missing key"):
        MandateStore.from_directory(tmp_path)
    bad.write_text("- agent: x\n  autonomy: L9\n")
    with pytest.raises(PolicyError):
        MandateStore.from_directory(tmp_path)
    bad.write_text("- [unclosed\n")
    with pytest.raises(PolicyError, match="invalid YAML"):
        MandateStore.from_directory(tmp_path)
    bad.write_text("- 42\n")
    with pytest.raises(PolicyError, match="expected a mapping"):
        MandateStore.from_directory(tmp_path)
