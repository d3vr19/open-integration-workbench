# Contributing to Open Integration Workbench

Thanks for helping build a Git-native, local-first engineering workbench
for SAP Cloud Integration content.

**Read first:** [`docs/contributor-guide/README.md`](docs/contributor-guide/README.md)
— environment setup, the safety checklist, and the log law.

**The quick version:**

1. `DEVELOPMENT_LOG.md` is the single source of truth. Read the latest
   entries before starting; append an entry with every PR.
2. All mutations flow through typed mechanisms (IR schema → runtime plugin
   → exporter shape). No raw file-edit tools, no guessed BPMN2 shapes —
   mirror reference bundles verbatim (the METHOD).
3. CI must stay green: CLI/Server/MCP/Gateway suites + ruff + SPA build.
   `pip install -e apps/cli[dev]` then `pytest` from `apps/cli`.
4. Never commit secrets or tenant URLs. `.env` is gitignored — keep it that way.
5. Good first contributions: **the Piece Recipe** (contributor-guide §8),
   FlowTest assertion types, example flows, law-registry entries, docs.

**Reporting problems:** use the issue templates — especially the
**teacher-request** template when the autonomous agent escalates instead
of guessing. Those reports feed the learning loop directly.
