# Pod security policy for every workload Regent ships.
#
# Evaluated by Conftest in CI on the rendered Kustomize output of each
# environment (`conftest test --namespace kubernetes`), and by OPA Gatekeeper
# at admission time in the cluster with the same rules. A manifest that fails
# here would be rejected by the cluster anyway; failing in CI is cheaper.
#
# Reading guide: each `deny` rule states one thing a pod must not do, and the
# message says which container and why.
package kubernetes

import rego.v1

workload_kinds := {"Deployment", "StatefulSet", "DaemonSet", "Job", "CronJob", "Rollout"}

is_workload if workload_kinds[input.kind]

# Pod template, whatever the wrapping kind.
pod_spec := input.spec.template.spec if {
	input.kind != "CronJob"
	is_workload
}

pod_spec := input.spec.jobTemplate.spec.template.spec if input.kind == "CronJob"

containers contains c if some c in pod_spec.containers

containers contains c if some c in pod_spec.initContainers

name := input.metadata.name

deny contains msg if {
	is_workload
	some c in containers
	c.securityContext.privileged == true
	msg := sprintf("%s/%s: container %q is privileged", [input.kind, name, c.name])
}

deny contains msg if {
	is_workload
	not pod_spec.securityContext.runAsNonRoot == true
	msg := sprintf("%s/%s: pod must set securityContext.runAsNonRoot: true", [input.kind, name])
}

deny contains msg if {
	is_workload
	some c in containers
	not c.securityContext.readOnlyRootFilesystem == true
	msg := sprintf("%s/%s: container %q must set readOnlyRootFilesystem: true", [input.kind, name, c.name])
}

deny contains msg if {
	is_workload
	some c in containers
	not c.securityContext.allowPrivilegeEscalation == false
	msg := sprintf("%s/%s: container %q must set allowPrivilegeEscalation: false", [input.kind, name, c.name])
}

deny contains msg if {
	is_workload
	some c in containers
	not "ALL" in c.securityContext.capabilities.drop
	msg := sprintf("%s/%s: container %q must drop ALL capabilities", [input.kind, name, c.name])
}

deny contains msg if {
	is_workload
	some c in containers
	not c.resources.limits.memory
	msg := sprintf("%s/%s: container %q has no memory limit", [input.kind, name, c.name])
}

deny contains msg if {
	is_workload
	some c in containers
	not c.resources.requests.cpu
	msg := sprintf("%s/%s: container %q has no cpu request", [input.kind, name, c.name])
}

deny contains msg if {
	is_workload
	some c in containers
	endswith(c.image, ":latest")
	msg := sprintf("%s/%s: container %q uses the mutable tag :latest", [input.kind, name, c.name])
}

deny contains msg if {
	is_workload
	some c in containers
	not contains(c.image, ":")
	not contains(c.image, "@")
	msg := sprintf("%s/%s: container %q has no tag or digest (defaults to :latest)", [input.kind, name, c.name])
}

deny contains msg if {
	is_workload
	input.kind in {"Deployment", "StatefulSet", "Rollout"}
	some c in pod_spec.containers
	not c.readinessProbe
	msg := sprintf("%s/%s: container %q has no readinessProbe", [input.kind, name, c.name])
}

deny contains msg if {
	is_workload
	input.kind in {"Deployment", "StatefulSet", "Rollout"}
	some c in pod_spec.containers
	not c.livenessProbe
	msg := sprintf("%s/%s: container %q has no livenessProbe", [input.kind, name, c.name])
}

deny contains msg if {
	is_workload
	pod_spec.hostNetwork == true
	msg := sprintf("%s/%s: hostNetwork is forbidden", [input.kind, name])
}

deny contains msg if {
	is_workload
	pod_spec.hostPID == true
	msg := sprintf("%s/%s: hostPID is forbidden", [input.kind, name])
}

deny contains msg if {
	is_workload
	not pod_spec.securityContext.seccompProfile.type == "RuntimeDefault"
	msg := sprintf("%s/%s: pod must set seccompProfile.type: RuntimeDefault", [input.kind, name])
}

deny contains msg if {
	is_workload
	not pod_spec.automountServiceAccountToken == false
	msg := sprintf("%s/%s: automountServiceAccountToken must be false unless the pod talks to the API server", [input.kind, name])
}
