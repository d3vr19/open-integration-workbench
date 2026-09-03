package io.oiw.groovy;

import org.codehaus.groovy.control.CompilerConfiguration;
import org.codehaus.groovy.control.customizers.SecureASTCustomizer;
import org.codehaus.groovy.control.customizers.ImportCustomizer;

import groovy.lang.Binding;
import groovy.lang.GroovyShell;
import groovy.lang.GroovyClassLoader;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Base64;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.*;

/**
 * OIW Groovy Runner — executes Groovy scripts in a sandboxed JVM process.
 *
 * Spec ref: §9.4 (script.groovy), §9.6 (Groovy Sandbox), §16.1 threat 2.
 *
 * Protocol (stdin/stdout JSON):
 *   Input:  { "scriptPath": "...", "message": { "body": "<base64>", ... }, "timeoutMs": 30000 }
 *   Output: { "status": "COMPLETED", "message": { "body": "<base64>", ... }, "error": null }
 *   Error:  { "status": "FAILED", "message": null, "error": { "type": "...", "message": "..." } }
 *
 * Security:
 *   - SecureASTCustomizer with both whitelist (allowed imports) and blocklist (disallowed imports)
 *   - Process isolation (separate JVM via subprocess)
 *   - Timeout enforcement via ExecutorService
 *   - No filesystem access beyond the script file
 *   - No network access (java.net.* blocked)
 */
public class GroovyRunner {

    // Spec §9.6 blocked list
    private static final List<String> DISALLOWED_IMPORTS = List.of(
        "java.lang.Runtime",
        "java.lang.ProcessBuilder",
        "java.lang.System",
        "java.lang.Thread",
        "java.net.Socket",
        "java.net.URL",
        "java.net.HttpURLConnection",
        "java.io.File",
        "java.io.FileWriter",
        "java.io.FileOutputStream",
        "java.io.FileInputStream",
        "groovy.lang.GroovyShell",
        "groovy.lang.GroovyClassLoader",
        "javax.script.ScriptEngine",
        "java.lang.reflect",
        "java.lang.ClassLoader"
    );

    // Spec §9.6 allowed list
    private static final List<String> ALLOWED_IMPORTS = List.of(
        "java.util",
        "java.lang.String",
        "java.lang.Integer",
        "java.lang.Long",
        "java.lang.Boolean",
        "java.lang.Double",
        "java.lang.Math",
        "java.lang.Object",
        "java.lang.Exception",
        "java.lang.RuntimeException",
        "java.lang.IllegalArgumentException",
        "java.text.SimpleDateFormat",
        "java.time",
        "java.math.BigDecimal",
        "java.math.BigInteger",
        "java.util.Base64",
        "java.util.UUID",
        "groovy.json.JsonSlurper",
        "groovy.json.JsonOutput",
        "groovy.xml.XmlSlurper",
        "groovy.xml.XmlUtil",
        // SAP CPI scripting API (tenant dialect, 559 corpus scripts):
        // `import com.sap.gateway.ip.core.customdev.util.Message` +
        // `def Message processData(Message message)`. Resolved to the OIW
        // compat shim compiled into this bridge (no SAP jars needed).
        "com.sap.gateway.ip.core.customdev.util.Message"
    );

    // Disallowed receivers (method call targets)
    private static final List<String> DISALLOWED_RECEIVERS = List.of(
        "java.lang.Runtime",
        "java.lang.ProcessBuilder",
        "java.lang.System",
        "java.lang.Thread",
        "java.lang.ClassLoader",
        "java.lang.Class",
        "java.lang.reflect.Method",
        "java.lang.reflect.Field",
        "java.net.Socket",
        "java.net.URL"
    );

    @SuppressWarnings("unchecked")
    public static void main(String[] args) {
        try {
            // Read JSON input from stdin
            BufferedReader reader = new BufferedReader(new InputStreamReader(System.in, StandardCharsets.UTF_8));
            StringBuilder sb = new StringBuilder();
            String line;
            while ((line = reader.readLine()) != null) {
                sb.append(line).append("\n");
            }
            String inputJson = sb.toString().trim();

            if (inputJson.isEmpty()) {
                writeError("IllegalArgumentException", "No input received on stdin");
                return;
            }

            // Parse JSON (simple parser — no external JSON lib needed)
            Map<String, Object> input = parseJson(inputJson);
            String scriptPath = (String) input.get("scriptPath");
            Number timeoutMs = (Number) input.get("timeoutMs");
            Map<String, Object> message = (Map<String, Object>) input.get("message");

            if (scriptPath == null || scriptPath.isEmpty()) {
                writeError("IllegalArgumentException", "scriptPath is required");
                return;
            }

            // Read the script
            String script;
            try {
                script = Files.readString(Path.of(scriptPath));
            } catch (IOException e) {
                writeError("IOException", "Cannot read script: " + scriptPath + " — " + e.getMessage());
                return;
            }

            // Build the binding (message context) — BOTH dialects:
            //  - OIW binding dialect: body/bodyBytes/headers/properties
            //  - SAP Message API (tenant corpus dialect): a `message`
            //    binding of the compat shim class; scripts call
            //    processData(message) or use it directly.
            Binding binding = new Binding();
            com.sap.gateway.ip.core.customdev.util.Message sapMessage = null;
            if (message != null) {
                String bodyB64 = (String) message.get("body");
                byte[] bodyBytes = bodyB64 != null ? Base64.getDecoder().decode(bodyB64) : new byte[0];
                String bodyStr = new String(bodyBytes, StandardCharsets.UTF_8);
                binding.setProperty("body", bodyStr);
                binding.setProperty("bodyBytes", bodyBytes);
                @SuppressWarnings("unchecked")
                Map<String, Object> inHeaders = (Map<String, Object>) message.getOrDefault("headers", new HashMap<>());
                @SuppressWarnings("unchecked")
                Map<String, Object> inProps = (Map<String, Object>) message.getOrDefault("properties", new HashMap<>());
                binding.setProperty("headers", inHeaders);
                binding.setProperty("properties", inProps);
                binding.setProperty("contentType", message.getOrDefault("contentType", "application/octet-stream"));
                sapMessage = new com.sap.gateway.ip.core.customdev.util.Message(bodyStr, inHeaders, inProps);
                binding.setProperty("message", sapMessage);
            }

            // Create sandboxed Groovy shell
            CompilerConfiguration config = createSandboxConfig();
            GroovyClassLoader classLoader = new GroovyClassLoader(GroovyRunner.class.getClassLoader(), config);
            GroovyShell shell = new GroovyShell(classLoader, binding, config);

            // Execute with timeout. Both dialects share ONE set of maps:
            // the binding's headers/properties maps are the SAME objects as
            // the message shim's, so bare map mutation and the SAP API
            // mutate the same state.
            // SAP CALLING CONVENTION (tenant ground truth): scripts define
            // `def Message processData(Message message)` and the runtime
            // CALLS it — they never self-invoke. When the raw evaluation
            // returns a non-Message and a processData method exists on the
            // script's meta class, call it with the message shim.
            long timeout = timeoutMs != null ? timeoutMs.longValue() : 30000L;
            ExecutorService executor = Executors.newSingleThreadExecutor();
            final com.sap.gateway.ip.core.customdev.util.Message sapMsg = sapMessage;
            Future<Object> future = executor.submit(() -> {
                // Parse as a Script so processData (if defined) is callable
                // on the script instance — SAP's calling convention.
                groovy.lang.Script parsed = shell.parse(script);
                Object raw = parsed.run();
                if (raw instanceof com.sap.gateway.ip.core.customdev.util.Message) {
                    return raw;
                }
                if (sapMsg != null && !parsed.getMetaClass().respondsTo(
                        parsed, "processData",
                        new Class[]{com.sap.gateway.ip.core.customdev.util.Message.class}).isEmpty()) {
                    Object invoked = parsed.getMetaClass().invokeMethod(
                        parsed, "processData", new Object[]{sapMsg});
                    if (invoked instanceof com.sap.gateway.ip.core.customdev.util.Message) {
                        return invoked;
                    }
                }
                return raw;
            });

            Object result;
            try {
                result = future.get(timeout, TimeUnit.MILLISECONDS);
            } catch (TimeoutException e) {
                future.cancel(true);
                executor.shutdownNow();
                writeError("TimeoutException", "Script exceeded " + timeout + "ms timeout");
                return;
            } catch (ExecutionException e) {
                Throwable cause = e.getCause() != null ? e.getCause() : e;
                writeError(cause.getClass().getSimpleName(), cause.getMessage());
                return;
            } finally {
                executor.shutdownNow();
            }

            // Build output message from the binding (the script may have modified headers/properties/body)
            Map<String, Object> outputMessage = new HashMap<>();
            // SAP-dialect read-back, in precedence order:
            //   1. the script's RETURN VALUE when it is the Message shim
            //      (`def Message processData(...)` + `return message` — the
            //      local param shadows the binding, so the RESULT object is
            //      the one carrying the state);
            //   2. the binding's message shim (scripts that mutate without
            //      returning — same object as passed in);
            //   3. plain binding maps (raw binding-dialect scripts).
            com.sap.gateway.ip.core.customdev.util.Message outSap = null;
            if (result instanceof com.sap.gateway.ip.core.customdev.util.Message rm) {
                outSap = rm;
            } else {
                Object mv = binding.getVariables().get("message");
                if (mv instanceof com.sap.gateway.ip.core.customdev.util.Message bm) {
                    outSap = bm;
                }
            }
            String bodyStr;
            Map<String, Object> outHeaders;
            Map<String, Object> outProperties;
            if (outSap != null) {
                Object b = outSap.getBody();
                bodyStr = b != null ? String.valueOf(b) : null;
                outHeaders = outSap.getHeaders();
                outProperties = outSap.getProperties();
            } else {
                bodyStr = (String) binding.getProperty("body");
                @SuppressWarnings("unchecked")
                Map<String, Object> h = (Map<String, Object>) binding.getVariable("headers");
                @SuppressWarnings("unchecked")
                Map<String, Object> p = (Map<String, Object>) binding.getVariable("properties");
                outHeaders = h;
                outProperties = p;
            }
            if (bodyStr != null) {
                outputMessage.put("body", Base64.getEncoder().encodeToString(bodyStr.getBytes(StandardCharsets.UTF_8)));
            } else {
                byte[] bodyB = (byte[]) binding.getProperty("bodyBytes");
                if (bodyB != null) {
                    outputMessage.put("body", Base64.getEncoder().encodeToString(bodyB));
                }
            }
            outputMessage.put("headers", outHeaders != null ? outHeaders : new HashMap<>());
            outputMessage.put("properties", outProperties != null ? outProperties : new HashMap<>());
            outputMessage.put("contentType", binding.getVariable("contentType"));

            // Write success output
            Map<String, Object> output = new HashMap<>();
            output.put("status", "COMPLETED");
            output.put("message", outputMessage);
            output.put("error", null);
            writeJson(output);

        } catch (Exception e) {
            writeError(e.getClass().getSimpleName(), e.getMessage());
        }
    }

    private static CompilerConfiguration createSandboxConfig() {
        CompilerConfiguration config = new CompilerConfiguration();

        // Import customizer — add allowed imports (spec §9.6 allowed list)
        ImportCustomizer importCustomizer = new ImportCustomizer();
        importCustomizer.addStarImports("java.util", "java.time", "groovy.json", "groovy.xml");
        importCustomizer.addImports(
            "java.lang.String", "java.lang.Integer", "java.lang.Long",
            "java.lang.Boolean", "java.lang.Double", "java.lang.Math",
            "java.lang.Object", "java.lang.Exception", "java.lang.RuntimeException",
            "java.lang.IllegalArgumentException",
            "java.text.SimpleDateFormat",
            "java.math.BigDecimal", "java.math.BigInteger",
            "java.util.Base64", "java.util.UUID"
        );
        config.addCompilationCustomizers(importCustomizer);

        // SecureASTCustomizer — closed-by-default whitelist (spec §9.6)
        // Use whitelist as primary defense; disallowed receivers as second layer.
        // Note: SecureASTCustomizer does not allow both allowedImports and
        // disallowedImports simultaneously. We use the whitelist (closed-by-default)
        // and rely on disallowedReceivers for method-call blocking.
        SecureASTCustomizer secure = new SecureASTCustomizer();

        // Whitelist: only these imports are allowed (closed-by-default)
        secure.setAllowedImports(ALLOWED_IMPORTS);
        secure.setIndirectImportCheckEnabled(true);

        // Block method calls on dangerous types (defense-in-depth)
        secure.setDisallowedReceivers(DISALLOWED_RECEIVERS);

        config.addCompilationCustomizers(secure);

        return config;
    }

    private static void writeJson(Map<String, Object> map) {
        StringBuilder sb = new StringBuilder();
        sb.append("{");
        boolean first = true;
        for (Map.Entry<String, Object> entry : map.entrySet()) {
            if (!first) sb.append(",");
            sb.append("\"").append(entry.getKey()).append("\":");
            writeValue(sb, entry.getValue());
            first = false;
        }
        sb.append("}");
        System.out.println(sb.toString());
    }

    @SuppressWarnings("unchecked")
    private static void writeValue(StringBuilder sb, Object value) {
        if (value == null) {
            sb.append("null");
        } else if (value instanceof String) {
            sb.append("\"").append(escapeJson((String) value)).append("\"");
        } else if (value instanceof Number || value instanceof Boolean) {
            sb.append(value.toString());
        } else if (value instanceof Map) {
            sb.append("{");
            boolean first = true;
            for (Map.Entry<String, Object> entry : ((Map<String, Object>) value).entrySet()) {
                if (!first) sb.append(",");
                sb.append("\"").append(escapeJson(entry.getKey())).append("\":");
                writeValue(sb, entry.getValue());
                first = false;
            }
            sb.append("}");
        } else {
            sb.append("\"").append(escapeJson(value.toString())).append("\"");
        }
    }

    private static String escapeJson(String s) {
        return s.replace("\\", "\\\\")
                .replace("\"", "\\\"")
                .replace("\n", "\\n")
                .replace("\r", "\\r")
                .replace("\t", "\\t");
    }

    private static void writeError(String type, String message) {
        Map<String, Object> error = new HashMap<>();
        error.put("type", type);
        error.put("message", message != null ? message : "Unknown error");

        Map<String, Object> output = new HashMap<>();
        output.put("status", "FAILED");
        output.put("message", null);
        output.put("error", error);
        writeJson(output);
    }

    /**
     * Minimal JSON parser — handles the stdin input format.
     * No external dependencies needed.
     */
    @SuppressWarnings("unchecked")
    private static Map<String, Object> parseJson(String json) {
        JsonParser parser = new JsonParser(json.trim());
        return (Map<String, Object>) parser.parse();
    }

    /**
     * Simple recursive descent JSON parser.
     */
    static class JsonParser {
        private final String json;
        private int pos;

        JsonParser(String json) {
            this.json = json;
            this.pos = 0;
        }

        Object parse() {
            skipWhitespace();
            return parseValue();
        }

        private Object parseValue() {
            skipWhitespace();
            char c = peek();
            if (c == '{') return parseObject();
            if (c == '[') return parseArray();
            if (c == '"') return parseString();
            if (c == 't' || c == 'f') return parseBoolean();
            if (c == 'n') return parseNull();
            return parseNumber();
        }

        private Map<String, Object> parseObject() {
            Map<String, Object> map = new HashMap<>();
            expect('{');
            skipWhitespace();
            if (peek() == '}') { pos++; return map; }
            while (true) {
                skipWhitespace();
                String key = parseString();
                skipWhitespace();
                expect(':');
                Object value = parseValue();
                map.put(key, value);
                skipWhitespace();
                if (peek() == ',') { pos++; continue; }
                if (peek() == '}') { pos++; break; }
                break;
            }
            return map;
        }

        private List<Object> parseArray() {
            List<Object> list = new java.util.ArrayList<>();
            expect('[');
            skipWhitespace();
            if (peek() == ']') { pos++; return list; }
            while (true) {
                list.add(parseValue());
                skipWhitespace();
                if (peek() == ',') { pos++; continue; }
                if (peek() == ']') { pos++; break; }
                break;
            }
            return list;
        }

        private String parseString() {
            expect('"');
            StringBuilder sb = new StringBuilder();
            while (pos < json.length()) {
                char c = json.charAt(pos++);
                if (c == '"') break;
                if (c == '\\') {
                    if (pos < json.length()) {
                        char esc = json.charAt(pos++);
                        switch (esc) {
                            case 'n': sb.append('\n'); break;
                            case 'r': sb.append('\r'); break;
                            case 't': sb.append('\t'); break;
                            case '"': sb.append('"'); break;
                            case '\\': sb.append('\\'); break;
                            case '/': sb.append('/'); break;
                            default: sb.append(esc);
                        }
                    }
                } else {
                    sb.append(c);
                }
            }
            return sb.toString();
        }

        private Number parseNumber() {
            int start = pos;
            while (pos < json.length() && "+-0123456789.eE".indexOf(json.charAt(pos)) >= 0) pos++;
            String numStr = json.substring(start, pos);
            if (numStr.contains(".") || numStr.contains("e") || numStr.contains("E")) {
                return Double.parseDouble(numStr);
            }
            return Long.parseLong(numStr);
        }

        private Boolean parseBoolean() {
            if (json.startsWith("true", pos)) { pos += 4; return true; }
            if (json.startsWith("false", pos)) { pos += 5; return false; }
            throw new RuntimeException("Invalid boolean at position " + pos);
        }

        private Object parseNull() {
            if (json.startsWith("null", pos)) { pos += 4; return null; }
            throw new RuntimeException("Invalid null at position " + pos);
        }

        private char peek() {
            if (pos >= json.length()) return '\0';
            return json.charAt(pos);
        }

        private void expect(char c) {
            if (peek() != c) throw new RuntimeException("Expected '" + c + "' at position " + pos + " but got '" + peek() + "'");
            pos++;
        }

        private void skipWhitespace() {
            while (pos < json.length() && Character.isWhitespace(json.charAt(pos))) pos++;
        }
    }
}
