# Terraform policy — the CloudGuard-IaC rules the organisation treats as
# non-negotiable, expressed for OPA so they can gate `terraform plan` too.
#
# Two input shapes are supported:
#   * HCL source, via `conftest test --parser hcl2 infra/terraform/` — a map of
#     `resource -> type -> name -> attributes` (what CI runs on the repository)
#   * a plan, via `terraform show -json plan.out | conftest test --namespace terraform -`
#     (what a deployment pipeline runs before `apply`)
package terraform

import rego.v1

admin_ports := {22, 3389, 3306, 5432, 6379, 27017, 9200, 2375, 2376}

# ---- normalise both shapes into `resources[{type, name, attrs}]` -------------

# The hcl2 parser wraps each named block in a list; a hand-written fixture may not.
resources contains r if {
	some type, named in input.resource
	some name, entries in named
	some attrs in as_list(entries)
	r := {"type": type, "name": name, "attrs": attrs}
}

resources contains r if {
	some rc in input.planned_values.root_module.resources
	r := {"type": rc.type, "name": rc.name, "attrs": rc.values}
}

resources contains r if {
	some module in input.planned_values.root_module.child_modules
	some rc in module.resources
	r := {"type": rc.type, "name": rc.name, "attrs": rc.values}
}

# ---- S3 ----------------------------------------------------------------------

deny contains msg if {
	some r in resources
	r.type == "aws_s3_bucket"
	startswith(r.attrs.acl, "public")
	msg := sprintf("aws_s3_bucket.%s: public ACL %q", [r.name, r.attrs.acl])
}

deny contains msg if {
	some r in resources
	r.type == "aws_s3_bucket_public_access_block"
	some flag in {"block_public_acls", "block_public_policy", "ignore_public_acls", "restrict_public_buckets"}
	not r.attrs[flag] == true
	msg := sprintf("aws_s3_bucket_public_access_block.%s: %s must be true", [r.name, flag])
}

# ---- security groups ---------------------------------------------------------

ingress_rules contains {"sg": r.name, "rule": rule} if {
	some r in resources
	r.type == "aws_security_group"
	some rule in as_list(r.attrs.ingress)
}

ingress_rules contains {"sg": r.name, "rule": rule} if {
	some r in resources
	r.type == "aws_security_group_rule"
	r.attrs.type == "ingress"
	rule := r.attrs
}

as_list(x) := x if is_array(x)

as_list(x) := [x] if is_object(x)

as_list(x) := [x] if is_string(x)

world_open(rule) if "0.0.0.0/0" in rule.cidr_blocks

world_open(rule) if "::/0" in rule.ipv6_cidr_blocks

deny contains msg if {
	some ir in ingress_rules
	world_open(ir.rule)
	some port in admin_ports
	ir.rule.from_port <= port
	ir.rule.to_port >= port
	msg := sprintf("security group %s: ingress from the world reaches administration port %d", [ir.sg, port])
}

deny contains msg if {
	some ir in ingress_rules
	world_open(ir.rule)
	ir.rule.protocol == "-1"
	msg := sprintf("security group %s: ingress from the world on every protocol", [ir.sg])
}

# ---- IAM ---------------------------------------------------------------------

deny contains msg if {
	some r in resources
	r.type in {"aws_iam_policy", "aws_iam_role_policy"}
	doc := json.unmarshal(r.attrs.policy)
	some st in as_list(doc.Statement)
	st.Effect == "Allow"
	"*" in as_list(st.Action)
	"*" in as_list(st.Resource)
	msg := sprintf("%s.%s: Allow * on * is an administrator grant", [r.type, r.name])
}

# ---- encryption --------------------------------------------------------------

deny contains msg if {
	some r in resources
	r.type == "aws_ebs_volume"
	not r.attrs.encrypted == true
	msg := sprintf("aws_ebs_volume.%s: not encrypted", [r.name])
}

deny contains msg if {
	some r in resources
	r.type in {"aws_db_instance", "aws_rds_cluster"}
	not r.attrs.storage_encrypted == true
	msg := sprintf("%s.%s: storage_encrypted must be true", [r.type, r.name])
}

deny contains msg if {
	some r in resources
	r.type == "aws_db_instance"
	r.attrs.publicly_accessible == true
	msg := sprintf("aws_db_instance.%s: publicly accessible", [r.name])
}

deny contains msg if {
	some r in resources
	r.type == "aws_ecr_repository"
	not r.attrs.image_tag_mutability == "IMMUTABLE"
	msg := sprintf("aws_ecr_repository.%s: tags must be IMMUTABLE so a signed digest cannot be swapped", [r.name])
}
