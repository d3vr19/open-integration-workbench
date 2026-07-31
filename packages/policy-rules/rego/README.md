# OIW Policy Rules — Rego (OPA)

Spec ref: §14.2 (Policy as Code). These Rego policies are the authoritative
policy definitions. The Python CLI implements the same rules inline (apps/cli/oiw/validators/rules.py)
for fast local validation; CI runs both for parity.

The Rego policies are not yet wired into the CLI (tracked as OW-008). They
run in CI via the `conftest` tool against the rendered IR.

## Rules

- `deny` — ERROR-level violations (block merge)
- `warn` — WARNING-level violations (visible but not blocking unless --strict)

Each rule carries its stable code (OIW-E0xx / OIW-W0xx) per spec §14.1.
