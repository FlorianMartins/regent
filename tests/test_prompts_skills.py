import pytest

from regent.gateway.prompts import PromptError, PromptRegistry, parse_prompt
from regent.skills import SkillRegistry
from regent.skills.loader import SkillError, parse_skill


def test_all_packaged_prompts_parse():
    reg = PromptRegistry()
    names = reg.names()
    assert {
        "verifier",
        "pr_reviewer",
        "ci_triage",
        "iac_guardian",
        "incident_triage",
        "dependency_steward",
        "release_scribe",
    } <= set(names)
    for name in names:
        p = reg.get(name)
        assert p.version and p.sha256 and "untrusted_data" in p.body, name


def test_prompt_render_and_missing_placeholder():
    p = parse_prompt("x", "---\nversion: '2'\n---\nHello {{name}} from {{repo}}")
    assert p.id == "x@2"
    assert p.render(name="a", repo="b") == "Hello a from b"
    with pytest.raises(PromptError, match="unfilled"):
        p.render(name="a")


def test_prompt_errors(tmp_path):
    with pytest.raises(PromptError, match="front-matter"):
        parse_prompt("x", "no front matter")
    with pytest.raises(PromptError, match="version"):
        parse_prompt("x", "---\ndescription: d\n---\nbody")
    with pytest.raises(PromptError, match="not shipped"):
        PromptRegistry().get("nope")
    with pytest.raises(PromptError, match="not found"):
        PromptRegistry(tmp_path).get("nope")
    (tmp_path / "custom.md").write_text("---\nversion: '9'\n---\nCustom")
    assert PromptRegistry(tmp_path).get("custom").version == "9"


def test_skills_registry_and_composition(tmp_path):
    reg = SkillRegistry()
    assert "secure-review" in reg.names()
    for_pr = reg.for_agent("pr-reviewer")
    assert {s.name for s in for_pr} >= {
        "secure-review",
        "conventional-commits",
        "kubernetes-baseline",
    }
    text = SkillRegistry.compose(for_pr)
    assert text.startswith("# Skills in force") and "## secure-review" in text
    assert SkillRegistry.compose([]) == ""
    (tmp_path / "org-rule").mkdir()
    (tmp_path / "org-rule" / "SKILL.md").write_text(
        "---\nname: org-rule\nversion: '1'\napplies_to: [nobody]\n---\nRule."
    )
    reg2 = SkillRegistry(tmp_path)
    assert "org-rule" in reg2.names()
    assert [s.name for s in reg2.for_agent("release-scribe", ("org-rule",))][-1] == "org-rule"
    with pytest.raises(SkillError, match="unknown skill"):
        reg2.get("missing")


def test_skill_parse_errors():
    with pytest.raises(SkillError, match="front-matter"):
        parse_skill("x", "body")
    with pytest.raises(SkillError, match="version"):
        parse_skill("x", "---\nname: x\n---\nbody")
    with pytest.raises(SkillError, match="invalid"):
        parse_skill("x", "---\n: [\n---\nbody")
