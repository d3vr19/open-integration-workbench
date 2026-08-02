#!/bin/bash
# OIW Groovy Runner wrapper
# Usage: echo '{"scriptPath":"...","message":{...},"timeoutMs":30000}' | oiw-groovy-runner.sh
DIR="$(cd "$(dirname "$0")" && pwd)"

# Check if JARs exist
if [ ! -f "$DIR/lib/groovy-4.0.22.jar" ]; then
    # JARs not available — output a FAILED response so Python falls back to stub
    echo '{"status":"FAILED","message":null,"error":{"type":"IOException","message":"Groovy JARs not found — JVM bridge unavailable"}}'
    exit 1
fi

# Check if compiled classes exist
if [ ! -d "$DIR/build/io" ]; then
    echo '{"status":"FAILED","message":null,"error":{"type":"ClassNotFoundException","message":"GroovyRunner not compiled — run javac first"}}'
    exit 1
fi

java -cp "$DIR/build:$DIR/lib/*" io.oiw.groovy.GroovyRunner
