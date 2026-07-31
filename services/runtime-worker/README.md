# `services/runtime-worker` — Java 21 process-isolated JVM (Phase 2)

> **Status: NOT YET IMPLEMENTED.**
> See `DEVELOPMENT_LOG.md` → Open Work item OW-003 and Deviation DEV-003.

When implemented, this will be the security-critical runtime that executes
Groovy scripts and XSLT transforms with:

- Process-isolated JVM (separate from the API server)
- No host filesystem access (read-only project mount)
- No network access (network namespace isolation)
- CPU: 1 core, Memory: 512 MB, Time: 30 s max
- seccomp-bpf syscall filter (Linux)
- Separate "trusted" profile for internal projects

The Python prototype in `apps/cli/oiw/runtime/` is the reference implementation
for the execution engine, message context, and step plugins. **It does NOT
enforce process isolation** — do not run untrusted Groovy in the Python runtime.

Spec ref: §5.1, §9.6 (Groovy Sandbox), §16.1 threat 2.
