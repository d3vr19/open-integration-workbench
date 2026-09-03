package com.sap.gateway.ip.core.customdev.util;

import java.util.HashMap;
import java.util.Map;

/**
 * OIW SAP-Message compat shim.
 *
 * Provides the com.sap.gateway.ip.core.customdev.util.Message API surface so
 * real tenant Groovy scripts (the dialect observed across the 559 Script
 * flows in the tenant corpus: `def Message processData(Message message)`
 * with getProperty/setProperty/getHeader/setHeader/getBody/setBody) run
 * UNCHANGED inside the OIW JVM bridge sandbox.
 *
 * The package/class names match SAP's public CPI scripting API exactly —
 * that is the point (scripts import it verbatim). The implementation is a
 * thin local shim over the bridge's binding maps; it performs no IO and no
 * network, inheriting the sandbox's process isolation + timeout guarantees.
 */
public class Message {

    private Object body;
    private final Map<String, Object> headers = new HashMap<>();
    private final Map<String, Object> properties = new HashMap<>();
    private Map<String, Object> exceptions = new HashMap<>();

    public Message(Object body, Map<String, Object> headers, Map<String, Object> properties) {
        this.body = body != null ? body : "";
        if (headers != null) this.headers.putAll(headers);
        if (properties != null) this.properties.putAll(properties);
    }

    // --- body ---

    public Object getBody() {
        return body;
    }

    public <T> T getBody(java.lang.Class<T> type) {
        if (body == null) return null;
        if (type == byte[].class && body instanceof String s) {
            return type.cast(s.getBytes(java.nio.charset.StandardCharsets.UTF_8));
        }
        if (type == String.class && !(body instanceof String)) {
            if (body instanceof byte[] b) {
                return type.cast(new String(b, java.nio.charset.StandardCharsets.UTF_8));
            }
            return type.cast(String.valueOf(body));
        }
        try {
            return type.cast(body);
        } catch (ClassCastException e) {
            return type.cast(String.valueOf(body));
        }
    }

    public void setBody(Object body) {
        this.body = body;
    }

    // --- headers ---

    public Object getHeader(String name) {
        return headers.get(name);
    }

    public void setHeader(String name, Object value) {
        headers.put(name, value);
    }

    public Map<String, Object> getHeaders() {
        return headers;
    }

    // --- properties ---

    public Object getProperty(String name) {
        return properties.get(name);
    }

    public void setProperty(String name, Object value) {
        properties.put(name, value);
    }

    public Map<String, Object> getProperties() {
        return properties;
    }

    // --- exceptions (SAP API surface; scripts read/add these) ---

    public void addAssociationException(String key, Object value) {
        if (exceptions == null) exceptions = new HashMap<>();
        exceptions.put(key, value);
    }

    public Map<String, Object> getAssociationExceptions() {
        return exceptions;
    }

    // --- string coercion helpers used by scripts ---

    @Override
    public String toString() {
        return String.valueOf(body);
    }
}
