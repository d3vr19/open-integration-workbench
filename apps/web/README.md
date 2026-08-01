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

## Not yet implemented

- Undo/redo (command pattern)
- Collaborative editing (presence)
- AI co-pilot panel (Phase 3 LLM integration in UI)
- Playwright E2E tests (OW-012)
- Generated TypeScript API client from OpenAPI (OW-015)

Spec ref: §6.1 (Front End), §10 (Visual Designer).
