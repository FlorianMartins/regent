package kubernetes

import rego.v1

good := {
	"kind": "Deployment",
	"metadata": {"name": "ok"},
	"spec": {"template": {"spec": {
		"automountServiceAccountToken": false,
		"securityContext": {"runAsNonRoot": true, "seccompProfile": {"type": "RuntimeDefault"}},
		"containers": [{
			"name": "app",
			"image": "ghcr.io/x/app:1.2.3",
			"securityContext": {"readOnlyRootFilesystem": true, "allowPrivilegeEscalation": false, "capabilities": {"drop": ["ALL"]}},
			"resources": {"requests": {"cpu": "100m", "memory": "64Mi"}, "limits": {"cpu": "1", "memory": "128Mi"}},
			"readinessProbe": {"httpGet": {"path": "/readyz", "port": 8080}},
			"livenessProbe": {"httpGet": {"path": "/healthz", "port": 8080}},
		}],
	}}},
}

test_good_deployment_passes if {
	count(deny) == 0 with input as good
}

test_latest_tag_denied if {
	bad := json.patch(good, [{"op": "replace", "path": "/spec/template/spec/containers/0/image", "value": "ghcr.io/x/app:latest"}])
	some msg in deny with input as bad
	contains(msg, ":latest")
}

test_untagged_image_denied if {
	bad := json.patch(good, [{"op": "replace", "path": "/spec/template/spec/containers/0/image", "value": "ghcr.io/x/app"}])
	some msg in deny with input as bad
	contains(msg, "no tag or digest")
}

test_privileged_denied if {
	bad := json.patch(good, [{"op": "add", "path": "/spec/template/spec/containers/0/securityContext/privileged", "value": true}])
	some msg in deny with input as bad
	contains(msg, "privileged")
}

test_root_denied if {
	bad := json.patch(good, [{"op": "remove", "path": "/spec/template/spec/securityContext/runAsNonRoot"}])
	some msg in deny with input as bad
	contains(msg, "runAsNonRoot")
}

test_missing_limits_denied if {
	bad := json.patch(good, [{"op": "remove", "path": "/spec/template/spec/containers/0/resources/limits"}])
	some msg in deny with input as bad
	contains(msg, "memory limit")
}

test_missing_probes_denied if {
	bad := json.patch(good, [{"op": "remove", "path": "/spec/template/spec/containers/0/readinessProbe"}])
	some msg in deny with input as bad
	contains(msg, "readinessProbe")
}

test_host_network_denied if {
	bad := json.patch(good, [{"op": "add", "path": "/spec/template/spec/hostNetwork", "value": true}])
	some msg in deny with input as bad
	contains(msg, "hostNetwork")
}

test_writable_root_denied if {
	bad := json.patch(good, [{"op": "replace", "path": "/spec/template/spec/containers/0/securityContext/readOnlyRootFilesystem", "value": false}])
	some msg in deny with input as bad
	contains(msg, "readOnlyRootFilesystem")
}

test_rollout_is_a_workload if {
	rollout := json.patch(good, [{"op": "replace", "path": "/kind", "value": "Rollout"}])
	count(deny) == 0 with input as rollout
	bad := json.patch(rollout, [{"op": "remove", "path": "/spec/template/spec/containers/0/livenessProbe"}])
	count(deny) == 1 with input as bad
}

test_non_workload_ignored if {
	count(deny) == 0 with input as {"kind": "Service", "metadata": {"name": "svc"}, "spec": {}}
}
