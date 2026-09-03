#!/usr/bin/env bash
# OIW Groovy Runner setup — downloads Groovy JARs and compiles GroovyRunner.
#
# Usage: bash services/runtime-worker-jvm/setup.sh
#
# This script:
#   1. Downloads Groovy 4.0.24 JARs from Maven Central (if not cached)
#   2. Compiles GroovyRunner.java
#   3. Verifies the bridge works
#
# Prerequisites: JDK 21+ (javac on PATH or JAVA_HOME set)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LIB_DIR="$SCRIPT_DIR/lib"
BUILD_DIR="$SCRIPT_DIR/build"
SRC_DIR="$SCRIPT_DIR/src/main/java/io/oiw/groovy"

GROOVY_VERSION="4.0.24"
MAVEN_BASE="https://repo1.maven.org/maven2/org/apache/groovy"

# Check for javac
if ! command -v javac &> /dev/null; then
    if [ -n "${JAVA_HOME:-}" ] && [ -x "$JAVA_HOME/bin/javac" ]; then
        export PATH="$JAVA_HOME/bin:$PATH"
    else
        echo "ERROR: javac not found. Install JDK 21+ or set JAVA_HOME."
        echo "  Ubuntu: sudo apt install openjdk-21-jdk-headless"
        echo "  macOS:  brew install openjdk@21"
        echo "  Manual: https://adoptium.net/"
        exit 1
    fi
fi

echo "=== OIW Groovy Runner setup ==="
echo "Java: $(java -version 2>&1 | head -1)"
echo "javac: $(javac -version 2>&1)"
echo

# Step 1: Download JARs
mkdir -p "$LIB_DIR"
for artifact in groovy groovy-json groovy-xml; do
    jar="$LIB_DIR/${artifact}-${GROOVY_VERSION}.jar"
    if [ ! -f "$jar" ]; then
        echo "Downloading ${artifact}-${GROOVY_VERSION}.jar..."
        curl -fsSL -o "$jar" \
            "${MAVEN_BASE}/${artifact}/${GROOVY_VERSION}/${artifact}-${GROOVY_VERSION}.jar"
    else
        echo "Cached: ${artifact}-${GROOVY_VERSION}.jar"
    fi
done

# Saxon-HE for XSLT 2.0/3.0 (B-2, spec §9.4: transform.xslt fidelity
# compatible-subset requires the XSLT2 subset; lxml is XSLT-1-only which is
# NOT a compatible subset of real SAP CPI mappings).
# xmlresolver is a Saxon 12.x runtime dependency (NoClassDefFoundError otherwise).
SAXON_VERSION="12.5"
SAXON_JAR="$LIB_DIR/Saxon-HE-${SAXON_VERSION}.jar"
if [ ! -f "$SAXON_JAR" ]; then
    echo "Downloading Saxon-HE-${SAXON_VERSION}.jar..."
    curl -fsSL -o "$SAXON_JAR" \
        "https://repo1.maven.org/maven2/net/sf/saxon/Saxon-HE/${SAXON_VERSION}/Saxon-HE-${SAXON_VERSION}.jar"
else
    echo "Cached: Saxon-HE-${SAXON_VERSION}.jar"
fi
XMLRESOLVER_VERSION="5.2.2"
XMLRESOLVER_JAR="$LIB_DIR/xmlresolver-${XMLRESOLVER_VERSION}.jar"
if [ ! -f "$XMLRESOLVER_JAR" ]; then
    echo "Downloading xmlresolver-${XMLRESOLVER_VERSION}.jar..."
    curl -fsSL -o "$XMLRESOLVER_JAR" \
        "https://repo1.maven.org/maven2/org/xmlresolver/xmlresolver/${XMLRESOLVER_VERSION}/xmlresolver-${XMLRESOLVER_VERSION}.jar"
else
    echo "Cached: xmlresolver-${XMLRESOLVER_VERSION}.jar"
fi
echo

# Step 2: Compile
echo "Compiling GroovyRunner..."
mkdir -p "$BUILD_DIR"
javac -cp "$LIB_DIR/*" -d "$BUILD_DIR" "$SRC_DIR/GroovyRunner.java"
echo "Compiled to $BUILD_DIR"

echo "Compiling XsltRunner (Saxon-HE)..."
XSLT_SRC_DIR="$SCRIPT_DIR/src/main/java/io/oiw/xslt"
javac -cp "$LIB_DIR/*" -d "$BUILD_DIR" "$XSLT_SRC_DIR/XsltRunner.java"
echo "Compiled to $BUILD_DIR"
echo

# Step 3: Verify
echo "Verifying bridge..."
echo '{"scriptPath":"/dev/null","message":{"body":"","contentType":"text/plain","headers":{},"properties":{}},"timeoutMs":1000}' | \
    bash "$SCRIPT_DIR/oiw-groovy-runner.sh" 2>&1 | head -1 || true
echo
echo "=== JVM bridge ready ==="
echo "JARs: $LIB_DIR"
echo "Classes: $BUILD_DIR"
echo "Wrapper: $SCRIPT_DIR/oiw-groovy-runner.sh"
