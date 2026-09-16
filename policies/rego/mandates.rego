# Invariants no agent mandate may break — the same rules as `regent policy-check`,
# in Rego so they can be enforced outside the Python process (a Gatekeeper
# ConstraintTemplate on a Mandate CRD, or Conftest on the YAML in CI).
#
# Input: one mandate document, or a list of them (`--parser yaml`).
package mandates

import rego.v1

mandates contains m if {
	is_array(input)
	some m in input
}

mandates contains input if is_object(input)

deny contains msg if {
	some m in mandates
	m.autonomy == "L4_ACT"
	msg := sprintf("mandate %q: L4_ACT (irreversible actions) is never granted", [m.agent])
}

deny contains msg if {
	some m in mandates
	some pattern in m.allowed_tools
	pattern in {"*", "**"}
	msg := sprintf("mandate %q: a wildcard allow-list defeats the point of a mandate", [m.agent])
}

deny contains msg if {
	some m in mandates
	m.budget.max_usd > 20
	msg := sprintf("mandate %q: budget %.2f USD exceeds the 20 USD per-run ceiling", [m.agent, m.budget.max_usd])
}

deny contains msg if {
	some m in mandates
	not m.agent
	msg := "a mandate without an agent name applies to nothing — and confuses everyone"
}

deny contains msg if {
	some m in mandates
	m.max_remote_class == "RESTRICTED"
	msg := sprintf("mandate %q: RESTRICTED data may never leave for a remote provider", [m.agent])
}

deny contains msg if {
	some m in mandates
	m.autonomy == "L3_ACT_REVERSIBLE"
	m.verification == "none"
	msg := sprintf("mandate %q: an agent that acts on its own must be verified (verification: none is refused at L3)", [m.agent])
}
