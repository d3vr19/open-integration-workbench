# `apps/web` — React SPA visual designer (Phase 2)

> **Status: SUBSTANTIALLY COMPLETE.**
> React 19 + Vite 8 + TypeScript + React Flow 11 + Tailwind CSS 4 + Monaco Editor.

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
- **AI co-pilot panel** (WP-04 Task 9): natural-language requirement →
  plan → approve → execute → diff. Calls `POST /agents:plan` and
  `POST /agents:implement`. Trajectory indicator shows recording status.
- **Truthful EMG panel** (OW-032 / WP-08 PR-10): displays persisted store counts + backend
  honesty chips; ⚡ badge reflects server-truth retrieval.
- **Playwright E2E tests in CI** (OW-026): `copilot.spec.ts` (2 tests) +
  `emg-insights.spec.ts` (2 tests) running in GitHub Actions via `.github/workflows/e2e.yaml`.
- **Generated API client** (OW-015 / WP-09 Task A-002): TypeScript schema generated from
  `packages/api-spec/openapi.yaml` into `src/api/gen/schema.d.ts`, wrapped by typed `ApiClient`
  in `src/api/client.ts` with stable boundary re-exports in `src/api.ts`.
- **Full SPA decomposition** (OW-029 / WP-09 Task A-003): `App.tsx` decomposed from 570 lines
  to 106 lines of pure layout using custom hooks (`useProjectWorkspace`, `useFlowEditor`,
  `useProjectActions`) and layout components (`AppHeader`, `LeftSidebar`, `CanvasArea`,
  `RightSidebar`). Scoped per-panel loading and error states without global error banner.
- **Trace Viewer v1.5** (WP-09 Tasks B-001 & B-002): Canvas node pass/fail/duration badges
  wired directly to `TraceInspector` (clicking a badge navigates to that step's exchange snapshot).
  Replay transport controls with step forward/backward and autoplay.

## Stack

| Layer | Choice | Status |
|-------|--------|--------|
| Framework | React 19 + TypeScript | ✓ |
| Graph canvas | React Flow 11 (`reactflow ^11.11.4`) | ✓ |
| Code editor | Monaco Editor | ✓ |
| State management | React hooks, no Zustand (Zustand planned for A-003) | Partial |
| Styling | Tailwind CSS 4 | ✓ |
| Build tool | Vite 8 (`vite ^8.2.0`) | ✓ |
| WebSocket | (via fetch + WebSocket API) | ✓ |
| API client | Generated from OpenAPI via `openapi-typescript` + typed wrapper (OW-015) | ✓ |

## Run

```bash
cd apps/web
npm install
npm run dev      # http://localhost:5173 (proxies /api to localhost:8000)
npm run build    # production build to dist/
npm run api:gen  # regenerate src/api/gen/schema.d.ts from packages/api-spec/openapi.yaml
```

## Not yet implemented

- Undo/redo (command pattern)
- Collaborative editing (presence)
- Real semantic diff in PatchPreviewDialog (OW-028 — currently derives from step results)

Spec ref: §6.1 (Front End), §10 (Visual Designer).
