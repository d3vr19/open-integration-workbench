# `apps/web` — React SPA visual designer (Phase 2)

> **Status: SUBSTANTIALLY COMPLETE.**
> React 19 + Vite 6 + TypeScript + React Flow 12 + Tailwind CSS 4 + Monaco Editor.

## What's implemented

- **Three-pane layout**: project explorer (left) / flow canvas (center) / properties + results (right)
- **Drag-and-drop**: 14 step types in palette, draggable onto canvas
- **Editable properties**: inline config editing, node ID editing
- **Monaco editor**: Groovy/XSLT/JSON Schema with syntax highlighting (vs-dark theme)
- **Tabbed canvas**: Flow Canvas / Resource Editor tabs
- **Simulation trace**: color-coded per-node trace entries + outbound calls
- **Semantic diff viewer**: structured diff with color-coded entries (added/modified/removed)
- **Action buttons**: Validate, Run Tests, Build, Simulate, View Diff, Git Status
- **Dirty-state tracking**: unsaved-changes indicator + Save button → PATCH flow

## Stack

| Layer | Choice | Status |
|-------|--------|--------|
| Framework | React 19 + TypeScript | ✓ |
| Graph canvas | React Flow 12 | ✓ |
| Code editor | Monaco Editor | ✓ |
| State management | React hooks (Zustand planned) | Partial |
| Styling | Tailwind CSS 4 | ✓ |
| Build tool | Vite 6 | ✓ |
| WebSocket | (via fetch + WebSocket API) | ✓ |
| API client | Hand-written (OW-015: generate from OpenAPI) | Partial |

## Run

```bash
cd apps/web
npm install
npm run dev    # http://localhost:5173 (proxies /api to localhost:8000)
npm run build  # production build to dist/
```

## Implemented

- Flow canvas (ReactFlow) with drag-and-drop palette
- Node properties panel with inline config editor
- Validation, test, build, simulate, diff panels
- Resource editor (schemas, scripts, mappings)
- **AI co-pilot panel** (WP-04 Task 9): natural-language requirement →
  plan → approve → execute → diff. Calls `POST /agents:plan` and
  `POST /agents:implement`. Trajectory indicator shows recording status.
- **Playwright E2E tests** (WP-04 Task 9): `test_copilot_suggest_and_apply`
  + `test_copilot_reject_plan` in `apps/web/e2e/copilot.spec.ts`.

## Not yet implemented

- Undo/redo (command pattern)
- Collaborative editing (presence)
- Full SPA decomposition (FlowCanvas/PropertiesPanel/PalettePanel extraction — OW-029)
- Playwright E2E in CI (OW-026 — tests pass locally but not yet wired into GitHub Actions)
- Generated TypeScript API client from OpenAPI (OW-015)
- Real semantic diff in PatchPreviewDialog (OW-028 — currently derives from step results)

Spec ref: §6.1 (Front End), §10 (Visual Designer).
