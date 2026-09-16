"""Skills: reusable, versioned know-how that agents load into their context.

A skill is a directory with a ``SKILL.md`` (YAML front-matter + Markdown).
It captures *how the organisation does things* — its Terraform conventions,
its incident-communication template, its Kubernetes hardening baseline — so
that every agent applies the same rules and a change to a rule is a pull
request, not a prompt tweak in someone's notebook.

Skills are content-addressed: the ledger records ``name@version`` and the
SHA-256 of what was actually loaded.
"""

from regent.skills.loader import Skill, SkillRegistry

__all__ = ["Skill", "SkillRegistry"]
