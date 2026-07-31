# Test Fixtures

Synthetic, publicly-derived, or hand-crafted fixtures for golden import/export
round-trip tests. **No customer artifacts.** (Spec §8.5.)

## Layout

```
test-fixtures/
├── minimal/
│   └── https-content-modifier-http/   # golden round-trip fixture
│       ├── source.zip                 # synthetic input archive
│       ├── expected-ir.yaml           # IR the importer must produce
│       ├── expected-export.zip        # deterministic export output
│       ├── import-report.yaml         # expected import report (§8.3)
│       └── roundtrip.diff             # known deviations (empty = none)
├── versioned/
│   ├── cpi-2024-Q3/                   # placeholder
│   └── cpi-2026-Q1/                   # placeholder
└── negative/
    ├── zip-bomb.zip                   # high compression ratio
    ├── path-traversal.zip             # ../ entries
    └── corrupt-manifest.zip           # invalid zip
```

## Regenerating fixtures

```bash
python scripts/generate_golden_fixture.py
python scripts/generate_negative_fixtures.py
```

## Adding a new fixture

1. Pick a name that describes the integration archetype (e.g. `soap-groovy-sftp`).
2. Create `test-fixtures/minimal/<name>/`.
3. Add `source.zip` (synthetic only — no customer artifacts).
4. Add `expected-ir.yaml` — the canonical IR the importer should produce.
5. Add `expected-export.zip` — the deterministic export output.
6. Add `import-report.yaml` — expected import report.
7. Add `roundtrip.diff` — known deviations (empty if none).
8. Add a test under `apps/cli/tests/test_golden_fixtures.py` that asserts the importer produces the expected IR.

Spec ref: §8.5 (Golden Fixture Repository), §8.4 (Round-Trip Policy).
