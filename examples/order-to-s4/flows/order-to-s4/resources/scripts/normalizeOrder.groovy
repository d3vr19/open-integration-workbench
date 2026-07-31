// normalizeOrder.groovy
// Spec ref: §26.3 reference scenario. DEV-003: this runs in a constrained
// stub interpreter (apps/cli/oiw/runtime/steps/groovy_script.py) for the
// Python prototype; full Groovy execution deferred to Phase 2.
//
// The stub supports a tiny subset:
//   message.setHeader('X', 'value')
//   message.setProperty('Y', 'value')
//   message.setBody('text')
//
// In production this would be full Groovy using the SAP Message API stubs
// (com.sap.it.api.mapping.MappingContext, org.apache.camel.Message).

def bodyText = message.getBody()
def region = "GLOBAL" // default

// Stub: set the region property so the router can branch on it.
// In the real Groovy implementation this would parse the JSON body and
// extract the region. The stub interpreter ignores unrecognised lines.
message.setProperty("region", "EU")
