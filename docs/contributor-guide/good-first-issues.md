# Good First Issues (seed list)

> Maintainers: promote these to GitHub issues with the `good first issue`
> label as capacity allows. Contributors: claim by commenting on the issue.

## Pieces (see the Piece Recipe, contributor-guide §8)

1. **`encoder.base64` exporter shape** — runtime plugin exists; the exporter
   has no BPMN2 mapping. Harvest a reference bundle, mirror verbatim.
2. **`validator.json-schema` exporter shape** — same pattern.
3. **`filter` piece promotion** — runtime + exporter exist and are
   live-plausible; needs a parity case (maintainer runs the oracle leg).
4. **`splitter.general` real-engine implementation** — currently a stub
   (simulated fidelity); a real splitter implementation unblocks the
   sftp-order-drop parity case.

## Runtime / semantics

5. **FlowTest assertion: `outbound.header.equals`** — assert outbound
   request headers (target, name, equals). Small, well-bounded.
6. **FlowTest assertion: `property.contains`** — substring assertions on
   exchange properties for looser matching.
7. **`oiw simulate` CLI verb** — the engine + trace exist (web UI uses
   them); expose a one-shot CLI command for terminal users.

## Workbench

8. **Trace panel: payload inspector** — the trace list shows summaries;
   expand a row to view full in/out body + headers (data already in
   TraceEntry.body_preview/headers).
9. **Dark/light theme toggle** — the CSS is dark-only.

## Docs

10. **`docs/adapter-fidelity.md`** — one table: every step type × its
    fidelity label × what local simulation covers vs what needs a tenant.
    15 rows of honesty, very high value for newcomers.

## Laws / learning loop

11. **Law registry consumer: `oiw validate --tenant-laws`** — read the
    live-learned law YAMLs and enforce them as warnings pre-deploy.
