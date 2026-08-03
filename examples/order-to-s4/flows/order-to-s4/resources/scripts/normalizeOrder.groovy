// normalizeOrder.groovy
// Spec ref: §26.3 reference scenario.
//
// Executed via the OIW JVM Groovy bridge (services/runtime-worker-jvm).
// The bridge provides: body (String), headers (Map), properties (Map), contentType (String).

import groovy.json.JsonSlurper

// Parse the body as JSON and extract the region
def json = new JsonSlurper().parseText(body)
properties["region"] = json.region ?: "GLOBAL"

// Add a normalization header
headers["X-Normalized-By"] = "oiw-groovy-bridge"
