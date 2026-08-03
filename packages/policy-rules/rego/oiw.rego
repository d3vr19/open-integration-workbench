# OIW Policy — Rego
# Spec ref: §14.2 (Policy as Code), §14.1 (rule codes).
#
# Input: { "flow": <IntegrationFlow IR>, "resources": { "<path>": "<content>" } }
# Output: deny[msg] and warn[msg] sets.

package oiw.policy

# OIW-E002: inline secrets in node config
deny[msg] {
    node := input.flow.spec.nodes[_]
    config_str := json.stringify(node.config)
    re_match(`(?i)(password|secret|api[_-]?key|token)["']?\s*[:=]\s*["'][^"']{6,}["']`, config_str)
    msg := sprintf("OIW-E002: inline secret detected in node '%s' config (flow '%s'); use credentialRef", [node.id, input.flow.metadata.id])
}

# OIW-E002: credentialRef must be a short identifier, not a long secret value
deny[msg] {
    node := input.flow.spec.nodes[_]
    cred := node.config.credentialRef
    is_string(cred)
    count(cred) > 200
    msg := sprintf("OIW-E002: credentialRef on node '%s' looks like an inline secret (length %d); use an identifier", [node.id, count(cred)])
}

# OIW-E003: unbounded splitter
deny[msg] {
    node := input.flow.spec.nodes[_]
    node.type == "splitter.general"
    not node.config.maxIterations
    not node.config.maxItems
    msg := sprintf("OIW-E003: splitter node '%s' has no maxIterations/maxItems (unbounded)", [node.id])
}

# OIW-E004: forbidden Groovy constructs
deny[msg] {
    node := input.flow.spec.nodes[_]
    node.type == "script.groovy"
    resource := node.config.resource
    content := input.resources[resource]
    contains(content, "Runtime.getRuntime")
    msg := sprintf("OIW-E004: script '%s' contains forbidden Runtime access", [resource])
}

deny[msg] {
    node := input.flow.spec.nodes[_]
    node.type == "script.groovy"
    resource := node.config.resource
    content := input.resources[resource]
    contains(content, "GroovyShell")
    msg := sprintf("OIW-E004: script '%s' contains forbidden GroovyShell", [resource])
}

# OIW-E005: insecure TLS (HTTP for sender/receiver)
deny[msg] {
    node := input.flow.spec.nodes[_]
    node.type == "receiver.http"
    startswith(node.config.url, "http://")
    msg := sprintf("OIW-E005: HTTP receiver '%s' must use TLS", [node.id])
}

# OIW-W001: missing timeout on receiver
warn[msg] {
    node := input.flow.spec.nodes[_]
    node.type == "receiver.http"
    not node.config.timeoutSeconds
    msg := sprintf("OIW-W001: receiver '%s' has no timeout configured", [node.id])
}

# OIW-W002: missing error handling
warn[msg] {
    not input.flow.spec.errorHandling
    msg := sprintf("OIW-W002: flow '%s' has no error-handling subprocess", [input.flow.metadata.id])
}

# OIW-W012: POST retry without idempotency key
warn[msg] {
    node := input.flow.spec.nodes[_]
    node.type == "receiver.http"
    upper(node.config.method) == "POST"
    node.config.retry.enabled == true
    not node.config.idempotencyKey
    not node.config.idempotencyKeyHeader
    msg := sprintf("OIW-W012: receiver '%s' retries POST without idempotency key", [node.id])
}
