// normalizeOrder.groovy — SAP Message API dialect (tenant ground truth:
// the 559 Script flows in the corpus all use processData(Message)).
// Executed by the OIW JVM Groovy bridge (SAP-compat Message shim).
import com.sap.gateway.ip.core.customdev.util.Message

def Message processData(Message message) {
    def body = message.getBody(java.lang.String) as String
    def json = new groovy.json.JsonSlurper().parseText(body)
    message.setProperty("region", json.region ?: "GLOBAL")
    message.setHeader("X-Normalized-By", "oiw-groovy-bridge")
    message.setBody(body)
    return message
}
