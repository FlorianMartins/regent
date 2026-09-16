package mandates

import rego.v1

ok := {"agent": "pr-reviewer", "autonomy": "L1_ADVISE", "allowed_tools": ["github.get_pr"], "budget": {"max_usd": 1.5}, "max_remote_class": "CONFIDENTIAL", "verification": "required"}

test_valid_mandate_passes if {
	count(deny) == 0 with input as ok
}

test_list_of_mandates if {
	count(deny) == 0 with input as [ok, ok]
}

test_l4_denied if {
	some msg in deny with input as object.union(ok, {"autonomy": "L4_ACT"})
	contains(msg, "L4_ACT")
}

test_wildcard_denied if {
	some msg in deny with input as object.union(ok, {"allowed_tools": ["*"]})
	contains(msg, "wildcard")
}

test_budget_ceiling if {
	some msg in deny with input as object.union(ok, {"budget": {"max_usd": 50}})
	contains(msg, "20 USD")
}

test_restricted_remote_denied if {
	some msg in deny with input as object.union(ok, {"max_remote_class": "RESTRICTED"})
	contains(msg, "RESTRICTED")
}

test_l3_without_verification_denied if {
	some msg in deny with input as object.union(ok, {"autonomy": "L3_ACT_REVERSIBLE", "verification": "none"})
	contains(msg, "verified")
}
