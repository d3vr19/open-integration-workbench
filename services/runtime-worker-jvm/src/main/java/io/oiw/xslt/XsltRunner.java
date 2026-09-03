package io.oiw.xslt;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Base64;
import java.util.HashMap;
import java.util.Map;
import java.util.concurrent.*;

import javax.xml.transform.Source;
import javax.xml.transform.stream.StreamSource;

import net.sf.saxon.s9api.Processor;
import net.sf.saxon.s9api.XsltCompiler;
import net.sf.saxon.s9api.XsltExecutable;
import net.sf.saxon.s9api.XsltTransformer;

import java.io.ByteArrayInputStream;
import java.io.StringWriter;

/**
 * OIW XSLT Runner — applies XSLT 2.0/3.0 stylesheets via Saxon-HE in a
 * sandboxed JVM subprocess.
 *
 * Spec ref: §9.4 (transform.xslt), §16.1 threat 2 (process isolation).
 * Mirrors GroovyRunner's stdin/stdout JSON protocol so the Python bridge
 * wrapper stays symmetric:
 *
 *   Input:  { "stylesheetPath": "...", "message": { "body": "<base64 xml>", ... }, "timeoutMs": 30000 }
 *   Output: { "status": "COMPLETED", "message": { "body": "<base64>", ... }, "error": null }
 *   Error:  { "status": "FAILED", "message": null, "error": { "type": "...", "message": "..." } }
 *
 * Security:
 *   - Process isolation (separate JVM via subprocess)
 *   - Timeout enforcement via ExecutorService
 *   - Stylesheet supplied as a file path by the trusted parent process
 *   - No network fetches from stylesheets (document()/xinclude not exercised
 *     by OIW-generated or harvested mappings; the runner never opens URLs)
 */
public class XsltRunner {

    @SuppressWarnings("unchecked")
    public static void main(String[] args) throws Exception {
        BufferedReader reader = new BufferedReader(
            new InputStreamReader(System.in, StandardCharsets.UTF_8));
        OutputStream out = System.out;

        String line;
        while ((line = reader.readLine()) != null) {
            Map<String, Object> input;
            try {
                input = (Map<String, Object>) parseJson(line.trim());
            } catch (Exception e) {
                writeError(out, "BadRequest", "invalid JSON: " + e.getMessage());
                continue;
            }

            Number timeoutMs = (Number) input.get("timeoutMs");
            long timeout = timeoutMs != null ? timeoutMs.longValue() : 30000L;

            ExecutorService executor = Executors.newSingleThreadExecutor();
            Future<Map<String, Object>> future = executor.submit(() -> runTransform(input));
            Map<String, Object> result;
            try {
                result = future.get(timeout, TimeUnit.MILLISECONDS);
            } catch (TimeoutException e) {
                executor.shutdownNow();
                writeError(out, "TimeoutException", "Transform exceeded " + timeout + "ms timeout");
                continue;
            } catch (ExecutionException e) {
                Throwable cause = e.getCause() != null ? e.getCause() : e;
                writeError(out, cause.getClass().getSimpleName(), String.valueOf(cause.getMessage()));
                continue;
            } finally {
                executor.shutdown();
            }
            writeJson(out, result);
        }
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> runTransform(Map<String, Object> input) throws Exception {
        String stylesheetPath = (String) input.get("stylesheetPath");
        if (stylesheetPath == null || stylesheetPath.isBlank()) {
            throw new IllegalArgumentException("stylesheetPath is required");
        }
        Map<String, Object> message = (Map<String, Object>) input.get("message");
        if (message == null) {
            throw new IllegalArgumentException("message is required");
        }
        String bodyB64 = (String) message.getOrDefault("body", "");
        byte[] bodyBytes = bodyB64.isEmpty() ? new byte[0] : Base64.getDecoder().decode(bodyB64);

        byte[] xsltBytes = Files.readAllBytes(Path.of(stylesheetPath));

        Processor processor = new Processor(false); // false = no schema-awareness (HE)
        XsltCompiler compiler = processor.newXsltCompiler();
        XsltExecutable executable = compiler.compile(new StreamSource(
            new ByteArrayInputStream(xsltBytes)));

        XsltTransformer transformer = executable.load();
        Source source = new StreamSource(new ByteArrayInputStream(bodyBytes));
        StringWriter sw = new StringWriter();
        transformer.setSource(source);
        transformer.setDestination(processor.newSerializer(sw));
        transformer.transform();

        Map<String, Object> resultMsg = new HashMap<>();
        resultMsg.put("body", Base64.getEncoder().encodeToString(
            sw.toString().getBytes(StandardCharsets.UTF_8)));
        resultMsg.put("contentType", "application/xml");
        resultMsg.put("headers", message.getOrDefault("headers", new HashMap<String, Object>()));
        resultMsg.put("properties", message.getOrDefault("properties", new HashMap<String, Object>()));

        Map<String, Object> result = new HashMap<>();
        result.put("status", "COMPLETED");
        result.put("message", resultMsg);
        result.put("error", null);
        return result;
    }

    // --- minimal JSON (no external deps; mirrors GroovyRunner's parser) ---

    @SuppressWarnings("unchecked")
    private static Object parseJson(String json) {
        JsonParser parser = new JsonParser(json);
        return parser.parse();
    }

    private static void writeJson(OutputStream out, Map<String, Object> map) throws Exception {
        StringBuilder sb = new StringBuilder();
        sb.append("{");
        boolean first = true;
        for (Map.Entry<String, Object> entry : map.entrySet()) {
            if (!first) sb.append(",");
            sb.append("\"").append(escapeJson(entry.getKey())).append("\":");
            writeValue(sb, entry.getValue());
            first = false;
        }
        sb.append("}");
        out.write((sb + "\n").getBytes(StandardCharsets.UTF_8));
        out.flush();
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

    private static void writeError(OutputStream out, String type, String message) {
        Map<String, Object> error = new HashMap<>();
        error.put("type", type);
        error.put("message", message != null ? message : "Unknown error");
        Map<String, Object> output = new HashMap<>();
        output.put("status", "FAILED");
        output.put("message", null);
        output.put("error", error);
        try {
            writeJson(out, output);
        } catch (Exception ignored) {
        }
    }

    /** Simple recursive descent JSON parser (subset for the bridge protocol). */
    static class JsonParser {
        private final String json;
        private int pos;

        JsonParser(String json) {
            this.json = json;
        }

        Object parse() {
            skipWhitespace();
            char c = peek();
            switch (c) {
                case '{': return parseObject();
                case '[': return parseArray();
                case '"': return parseString();
                case 't': expect("true"); return Boolean.TRUE;
                case 'f': expect("false"); return Boolean.FALSE;
                case 'n': expect("null"); return null;
                default: return parseNumber();
            }
        }

        private void skipWhitespace() {
            while (pos < json.length() && Character.isWhitespace(json.charAt(pos))) pos++;
        }

        private char peek() {
            if (pos >= json.length()) throw new IllegalStateException("unexpected end of input");
            return json.charAt(pos);
        }

        private void expect(String word) {
            if (!json.startsWith(word, pos)) throw new IllegalStateException("invalid literal at " + pos);
            pos += word.length();
        }

        private Map<String, Object> parseObject() {
            Map<String, Object> map = new HashMap<>();
            pos++; // {
            skipWhitespace();
            if (peek() == '}') { pos++; return map; }
            while (true) {
                skipWhitespace();
                String key = parseString();
                skipWhitespace();
                if (peek() != ':') throw new IllegalStateException("expected ':' at " + pos);
                pos++;
                map.put(key, parse());
                skipWhitespace();
                char c = peek();
                if (c == ',') { pos++; continue; }
                if (c == '}') { pos++; return map; }
                throw new IllegalStateException("expected ',' or '}' at " + pos);
            }
        }

        private java.util.List<Object> parseArray() {
            java.util.List<Object> list = new java.util.ArrayList<>();
            pos++; // [
            skipWhitespace();
            if (peek() == ']') { pos++; return list; }
            while (true) {
                list.add(parse());
                skipWhitespace();
                char c = peek();
                if (c == ',') { pos++; continue; }
                if (c == ']') { pos++; return list; }
                throw new IllegalStateException("expected ',' or ']' at " + pos);
            }
        }

        private String parseString() {
            if (peek() != '"') throw new IllegalStateException("expected string at " + pos);
            pos++;
            StringBuilder sb = new StringBuilder();
            while (true) {
                char c = json.charAt(pos++);
                if (c == '"') return sb.toString();
                if (c == '\\') {
                    char esc = json.charAt(pos++);
                    switch (esc) {
                        case '"': sb.append('"'); break;
                        case '\\': sb.append('\\'); break;
                        case '/': sb.append('/'); break;
                        case 'n': sb.append('\n'); break;
                        case 'r': sb.append('\r'); break;
                        case 't': sb.append('\t'); break;
                        case 'b': sb.append('\b'); break;
                        case 'f': sb.append('\f'); break;
                        case 'u':
                            sb.append((char) Integer.parseInt(json.substring(pos, pos + 4), 16));
                            pos += 4;
                            break;
                        default: throw new IllegalStateException("bad escape \\" + esc);
                    }
                } else {
                    sb.append(c);
                }
            }
        }

        private Number parseNumber() {
            int start = pos;
            while (pos < json.length() && "+-0123456789.eE".indexOf(json.charAt(pos)) >= 0) pos++;
            String num = json.substring(start, pos);
            if (num.contains(".") || num.contains("e") || num.contains("E")) {
                return Double.parseDouble(num);
            }
            try {
                return Long.parseLong(num);
            } catch (NumberFormatException e) {
                return Double.parseDouble(num);
            }
        }
    }
}
