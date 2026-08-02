# OIW Groovy Runner (JVM Bridge)

> **Phase 3 — P1a: Real Groovy execution via sandboxed JVM.**
> Spec ref: §9.4 (script.groovy), §9.6 (Groovy Sandbox), §16.1 threat 2.

Executes Groovy scripts in a sandboxed JVM process with `SecureASTCustomizer`
for import/receiver blocking. Called by the Python `groovy_script.py` step
plugin via `subprocess.run()`.

## Architecture

```
Python groovy_script.py
  │  subprocess.run(["bash", "oiw-groovy-runner.sh"], input=json)
  ▼
oiw-groovy-runner.sh
  │  java -cp "build:lib/*" io.oiw.groovy.GroovyRunner
  ▼
GroovyRunner.java
  │  SecureASTCustomizer (disallowed imports + receivers)
  │  GroovyShell.evaluate(script)
  │  ExecutorService with timeout
  ▼
Groovy script executes:
  - headers["X-Key"] = "value"
  - properties["name"] = "value"
  - body = JsonOutput.toJson(json)
  - JsonSlurper().parseText(body)
```

## Protocol (stdin/stdout JSON)

**Input:**
```json
{
  "scriptPath": "/tmp/script.groovy",
  "message": {
    "body": "<base64-encoded bytes>",
    "contentType": "application/json",
    "headers": {"Content-Type": "application/json"},
    "properties": {"sourceSystem": "S4"}
  },
  "timeoutMs": 30000
}
```

**Output (success):**
```json
{
  "status": "COMPLETED",
  "message": {
    "body": "<base64-encoded bytes>",
    "headers": {"X-Test": "hello"},
    "properties": {"processed": "true"},
    "contentType": "application/json"
  },
  "error": null
}
```

**Output (failure):**
```json
{
  "status": "FAILED",
  "message": null,
  "error": {
    "type": "SecurityException",
    "message": "Importing [java.lang.Runtime] is not allowed"
  }
}
```

## Security

- **SecureASTCustomizer**: blocks `java.lang.Runtime`, `ProcessBuilder`, `System`, `Thread`, `java.net.*`, `java.io.File*`, `GroovyShell`, `GroovyClassLoader`, `javax.script.*`, `java.lang.reflect.*`
- **Process isolation**: separate JVM process per invocation
- **Timeout**: 30s default, enforced by `ExecutorService`
- **No filesystem access**: script is passed via temp file, no project mount
- **No network access**: `java.net.*` is blocked by the customizer

## Build

```bash
export JAVA_HOME=/path/to/jdk-21
cd services/runtime-worker-jvm
javac -cp "lib/*" -d build src/main/java/io/oiw/groovy/GroovyRunner.java
```

The Python step plugin automatically finds the bridge via `OIW_HOME` env var
or by traversing up to the repo root. If the bridge is not found, it falls
back to the stub interpreter (DEV-003).

## Tests

4 tests in `apps/cli/tests/test_groovy_jvm.py`:
1. Header set — Groovy script sets a header → assert header in output
2. Body transform — Groovy script transforms JSON body → assert body changed
3. Runtime.exec blocked — Groovy script with `Runtime.getRuntime()` → assert FAILED
4. Timeout killed — Groovy script with infinite loop → assert timeout + process killed

Tests are skipped if the JVM bridge is not available.
