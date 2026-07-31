# OIW Visual Designer (apps/web)

> **Phase 2 — Visual Workbench (spec §10).**
> Status: **MINIMAL PROTOTYPE** — project explorer, flow canvas, properties panel,
> validation panel, test runner panel, and build panel are functional.
> Drag-and-drop editing, Monaco editor, and WebSocket trace streaming are not yet
> implemented (tracked as OW-016).

## Stack

Per spec §6.1:

| Layer | Choice | Status |
|-------|--------|--------|
| Framework | React 19 + TypeScript 5.5 | ✓ (React 19 via Vite) |
| Graph canvas | React Flow 12 | ✓ |
| Code editor | Monaco Editor | Not yet |
| State management | Zustand + TanStack Query | Not yet (using React hooks) |
| Styling | Tailwind CSS 4 + Radix UI primitives | ✓ Tailwind; Radix not yet |
| Build tool | Vite 6 | ✓ |
| WebSocket | socket.io-client | Not yet |
| API client | Generated from OpenAPI 3.1 | Not yet (hand-written; OW-015) |
| Design system | Original — dark theme | ✓ |

## Run (development)

```bash
# From the repo root — start the API server first
pip install -e apps/cli
pip install -e apps/server-python-prototype
OIW_WORKSPACE=$(pwd)/examples uvicorn oiw_server.main:app --reload --port 8000

# In a separate terminal — start the SPA
cd apps/web
npm install
npm run dev
```

Open http://localhost:5173. The Vite dev server proxies `/api` to localhost:8000.

## Build

```bash
cd apps/web
npm run build
# Output: dist/
```

## Features

### Implemented

- **Project explorer** — lists projects from the workspace; select to view flows.
- **Flow canvas** — React Flow 12 with dark theme; nodes from `diagram.json`; edges with conditional labels.
- **Properties panel** — click a node to see its ID, type, fidelity, and config.
- **Validation panel** — click "Validate" to run `oiw validate --strict` and see results.
- **Test runner panel** — click "Run Tests" to run `oiw test --all` and see pass/fail per test.
- **Build panel** — click "Build" to run `oiw build` and see the digest + entry count.
- **Git status bar** — shows branch, HEAD SHA, dirty flag, and last build digest.

### Not yet implemented

- Drag-and-drop node creation
- Inline node editing (properties panel is read-only)
- Monaco code editor for Groovy/XSLT/JSON Schema resources
- WebSocket trace streaming during simulation
- Semantic diff viewer
- Undo/redo
- Collaborative editing (presence)
- AI co-pilot panel (Phase 3)

## Architecture

```
src/
├── main.tsx          # React entry point
├── App.tsx           # Main app — three-pane layout
├── App.css           # Original dark-theme styles
├── index.css         # Tailwind import + CSS variables
├── api.ts            # Hand-written API client (OW-015: generate from OpenAPI)
└── flow-utils.ts     # IR → React Flow node/edge conversion
```

Spec ref: §10.3 (Component Architecture) — the full target structure is more
granular; this is the minimal starter.
