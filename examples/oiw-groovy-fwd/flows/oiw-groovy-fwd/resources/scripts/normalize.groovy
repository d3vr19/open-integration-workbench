// OIW parity case — SAP Message API dialect (the JVM bridge's canonical
// dialect; matches the tenant corpus's 559 Script flows).
import com.sap.gateway.ip.core.customdev.util.Message

def Message processData(Message message) {
    def body = message.getBody(java.lang.String) as String
    message.setProperty("source", "oiw-groovy-fwd")
    message.setHeader("X-Normalized-By", "oiw-groovy-bridge")
    message.setBody(body)
    return message
}
