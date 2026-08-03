# OIW CLI (`apps/cli`)

The `oiw` command-line interface — the Git-native headless core of Open Integration Workbench.

> **Phase 0/1 implementation language is Python.**
> Spec §6.2 mandates Kotlin 2.1 + Spring Boot 3.4 + picocli for the production CLI.
> Python was chosen for the bootstrap to validate the architecture fast.
> See [`DEVELOPMENT_LOG.md` ADR-PY-001](../../DEVELOPMENT_LOG.md#adr-py-001-phase-01-implementation-language-is-python-deviation-from-spec-62) for the rationale and migration plan.
> The IR JSON Schemas, Rego policies, Semgrep rules, and test fixtures are language-agnostic and survive the migration unchanged.

## Install (development mode)

```bash
cd apps/cli
pip install -e .
```

## Commands

| Command | Spec ref | Description |
|---------|---------|-------------|
| `oiw init <path> --archetype <name>` | §11.1, §19 Phase 1 | Create a new project skeleton |
| `oiw validate [--strict]` | §14 | Validate project + flows + tests against IR schemas and rule engine |
| `oiw test [--all \| --flow <id> \| --test <name>]` | §17 | Run flow tests |
| `oiw build --target <profile>` | §8 | Compile IR to a target-profile artifact package in `dist/` |
| `oiw diff [<rev>]` | §10.5 | Show semantic diff between revisions |
| `oiw import <archive.zip>` | §8.2 | Import a SAP-compatible archive into IR (minimal MVP) |
| `oiw git status` | §11 | Show Git status + last build digest |
| `oiw archive inspect <zip>` | §8.2 | Safe archive inspection (zip-bomb / path-traversal defense) |

## Examples

```bash
# Validate the reference scenario
cd examples/order-to-s4
oiw validate --strict

# Run all tests
oiw test --all

# Build a target artifact
oiw build --target sap-cloud-integration-2026-07

# Inspect an imported archive safely
oiw archive inspect path/to/artifact.zip
```

## Architecture

```
apps/cli/oiw/
├── __init__.py
├── cli.py                  # Click entry point
├── project.py              # Project + flow + resource loader
├── schema_validator.py     # JSON Schema validator (loads packages/ir-schema/schemas/*.json)
├── archive.py              # Safe archive inspector (spec §8.2)
├── diff.py                 # Semantic diff engine (spec §10.5)
├── git_ops.py              # Git status + commit proposal (spec §11)
├── testing.py              # FlowTest runner (spec §17)
├── compiler/
│   ├── __init__.py
│   ├── import_parser.py    # Minimal import parser (spec §8.2)
│   ├── export.py           # Deterministic export compiler (spec §8.4)
│   └── report.py           # Import report generator (spec §8.3)
├── validators/
│   ├── __init__.py
│   ├── graph.py            # Semantic graph validation (connectedness, cycles)
│   └── rules.py            # Rule codes OIW-E001..E007, OIW-W001..W012 (spec §14.1)
└── runtime/
    ├── __init__.py
    ├── context.py          # MessageContext (spec §9.1)
    ├── engine.py           # ExecutionPlan, topological sort, step execution (spec §9.2)
    ├── steps/              # Step plugin implementations (spec §9.4)
    │   ├── __init__.py
    │   ├── base.py         # StepPlugin SPI (spec §9.3)
    │   ├── http_sender.py
    │   ├── content_modifier.py
    │   ├── groovy_script.py
    │   ├── xslt_transform.py
    │   ├── router.py
    │   ├── http_receiver.py
    │   ├── json_schema_validator.py
    │   └── log_step.py
    └── trace.py            # Trace entry + streaming (spec §9.2 step 8)
```
