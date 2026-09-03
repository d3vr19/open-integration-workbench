#!/bin/bash
# OIW XSLT Runner wrapper (Saxon-HE)
# Usage: echo '{"stylesheetPath":"...","message":{...},"timeoutMs":30000}' | oiw-xslt-runner.sh
DIR="$(cd "$(dirname "$0")" && pwd)"

if ! ls "$DIR"/lib/Saxon-HE-*.jar > /dev/null 2>&1; then
    echo '{"status":"FAILED","message":null,"error":{"type":"IOException","message":"Saxon-HE JAR not found — run setup.sh (B-2 XSLT2 bridge)"}}'
    exit 1
fi

if [ ! -d "$DIR/build/io" ]; then
    echo '{"status":"FAILED","message":null,"error":{"type":"ClassNotFoundException","message":"XsltRunner not compiled — run setup.sh"}}'
    exit 1
fi

java -cp "$DIR/build:$DIR/lib/*" io.oiw.xslt.XsltRunner
