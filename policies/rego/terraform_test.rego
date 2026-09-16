package terraform

import rego.v1

hcl := {"resource": {
	"aws_s3_bucket": {"logs": {"bucket": "x"}},
	"aws_s3_bucket_public_access_block": {"logs": {"block_public_acls": true, "block_public_policy": true, "ignore_public_acls": true, "restrict_public_buckets": true}},
	"aws_security_group": {"web": {"ingress": [{"from_port": 443, "to_port": 443, "protocol": "tcp", "cidr_blocks": ["0.0.0.0/0"]}]}},
	"aws_ecr_repository": {"app": {"image_tag_mutability": "IMMUTABLE"}},
}}

test_clean_hcl_passes if {
	count(deny) == 0 with input as hcl
}

test_public_acl_denied if {
	bad := json.patch(hcl, [{"op": "add", "path": "/resource/aws_s3_bucket/logs/acl", "value": "public-read"}])
	some msg in deny with input as bad
	contains(msg, "public ACL")
}

test_public_access_block_flags if {
	bad := json.patch(hcl, [{"op": "replace", "path": "/resource/aws_s3_bucket_public_access_block/logs/block_public_acls", "value": false}])
	some msg in deny with input as bad
	contains(msg, "block_public_acls")
}

test_ssh_from_world_denied if {
	bad := json.patch(hcl, [{"op": "replace", "path": "/resource/aws_security_group/web/ingress/0/from_port", "value": 22}, {"op": "replace", "path": "/resource/aws_security_group/web/ingress/0/to_port", "value": 22}])
	some msg in deny with input as bad
	contains(msg, "port 22")
}

test_all_protocols_denied if {
	bad := json.patch(hcl, [{"op": "replace", "path": "/resource/aws_security_group/web/ingress/0/protocol", "value": "-1"}])
	some msg in deny with input as bad
	contains(msg, "every protocol")
}

test_iam_star_denied if {
	bad := json.patch(hcl, [{"op": "add", "path": "/resource/aws_iam_policy", "value": {"admin": {"policy": "{\"Statement\":[{\"Effect\":\"Allow\",\"Action\":\"*\",\"Resource\":\"*\"}]}"}}}])
	some msg in deny with input as bad
	contains(msg, "administrator")
}

test_mutable_ecr_denied if {
	bad := json.patch(hcl, [{"op": "replace", "path": "/resource/aws_ecr_repository/app/image_tag_mutability", "value": "MUTABLE"}])
	some msg in deny with input as bad
	contains(msg, "IMMUTABLE")
}

test_plan_shape if {
	plan := {"planned_values": {"root_module": {"resources": [{"type": "aws_db_instance", "name": "db", "values": {"storage_encrypted": false, "publicly_accessible": true}}]}}}
	count(deny) == 2 with input as plan
}
