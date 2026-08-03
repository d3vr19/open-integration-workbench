import { useCallback, useState, useEffect, useRef } from 'react';
import ReactFlow, {
  Background,
  Controls,
  MiniMap,
  addEdge as rfAddEdge,
  type Connection,
  type Edge,
  type Node,
  type NodeMouseHandler,
  type OnNodesDelete,
  type OnEdgesDelete,
} from 'reactflow';
import 'reactflow/dist/style.css';
import './App.css';

import { api } from './api';
import type { ProjectSummary, FlowSummary, IntegrationFlow, ValidationResult, TestResult, BuildResult, GitStatus, SimulationResult, TraceEntry, ResourceSummary, StructuredDiff } from './api';
import { toReactFlowNodes, toReactFlowEdges, fidelityColor } from './flow-utils';
import { ResourceEditor } from './ResourceEditor';
import { DiffViewer } from './DiffViewer';
import { CoPilotPanel } from './components/llm/CoPilotPanel';

// Available step types for the palette (spec §9.4)
const PALETTE_STEPS = [
  { type: 'modifier.content', name: 'Content Modifier', fidelity: 'compatible-subset' },
  { type: 'validator.json-schema', name: 'JSON Schema Validator', fidelity: 'compatible-subset' },
  { type: 'script.groovy', name: 'Groovy Script', fidelity: 'simulated' },
  { type: 'transform.xslt', name: 'XSLT Transform', fidelity: 'compatible-subset' },
  { type: 'router.content-based', name: 'Content Router', fidelity: 'compatible-subset' },
  { type: 'filter', name: 'Filter', fidelity: 'compatible-subset' },
  { type: 'converter.json-to-xml', name: 'JSON → XML', fidelity: 'compatible-subset' },
  { type: 'converter.xml-to-json', name: 'XML → JSON', fidelity: 'compatible-subset' },
  { type: 'encoder.base64', name: 'Base64 Encoder', fidelity: 'compatible-subset' },
  { type: 'splitter.general', name: 'Splitter', fidelity: 'simulated' },
  { type: 'gather', name: 'Gather', fidelity: 'simulated' },
  { type: 'receiver.http', name: 'HTTP Receiver', fidelity: 'simulated' },
  { type: 'receiver.sftp', name: 'SFTP Receiver', fidelity: 'simulated' },
  { type: 'log.message', name: 'Log', fidelity: 'compatible-subset' },
];

let nodeIdCounter = 0;
function genNodeId(type: string): string {
  nodeIdCounter += 1;
  const prefix = type.split('.').pop() || 'node';
  return `${prefix}-${Date.now().toString(36).slice(-4)}-${nodeIdCounter}`;
}

function App() {
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [selectedProject, setSelectedProject] = useState<string | null>(null);
  const [flows, setFlows] = useState<FlowSummary[]>([]);
  const [selectedFlow, setSelectedFlow] = useState<string | null>(null);
  const [flow, setFlow] = useState<IntegrationFlow | null>(null);
  const [rfNodes, setRfNodes] = useState<Node[]>([]);
  const [rfEdges, setRfEdges] = useState<Edge[]>([]);
  const [selectedNode, setSelectedNode] = useState<Node | null>(null);
  const [validation, setValidation] = useState<ValidationResult | null>(null);
  const [tests, setTests] = useState<TestResult[] | null>(null);
  const [build, setBuild] = useState<BuildResult | null>(null);
  const [gitStatus, setGitStatus] = useState<GitStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pendingOps, setPendingOps] = useState<unknown[]>([]);
  const [dirty, setDirty] = useState(false);
  const [simulation, setSimulation] = useState<SimulationResult | null>(null);
  const [simulating, setSimulating] = useState(false);
  const [resources, setResources] = useState<ResourceSummary[]>([]);
  const [selectedResource, setSelectedResource] = useState<ResourceSummary | null>(null);
  const [viewMode, setViewMode] = useState<'canvas' | 'resource'>('canvas');
  const [diff, setDiff] = useState<StructuredDiff | null>(null);
  const dragType = useRef<string | null>(null);

  // Load project list on mount
  useEffect(() => {
    api.listProjects().then(setProjects).catch((e) => setError(String(e)));
  }, []);

  // Load flows when a project is selected
  useEffect(() => {
    if (!selectedProject) return;
    setFlows([]);
    setSelectedFlow(null);
    setFlow(null);
    setPendingOps([]);
    setDirty(false);
    setResources([]);
    setSelectedResource(null);
    setViewMode('canvas');
    api.listFlows(selectedProject).then(setFlows).catch((e) => setError(String(e)));
    api.listResources(selectedProject).then(setResources).catch((e) => setError(String(e)));
  }, [selectedProject]);

  // Load flow when selected — sync RF nodes/edges
  useEffect(() => {
    if (!selectedProject || !selectedFlow) return;
    setFlow(null);
    setPendingOps([]);
    setDirty(false);
    setSelectedNode(null);
    api.getFlow(selectedProject, selectedFlow).then((f) => {
      setFlow(f);
      setRfNodes(toReactFlowNodes(f));
      setRfEdges(toReactFlowEdges(f));
    }).catch((e) => setError(String(e)));
  }, [selectedProject, selectedFlow]);

  // Refresh the current flow after an external mutation (e.g. the
  // co-pilot agent applied a patch). Re-fetches the flow IR and
  // syncs the ReactFlow canvas.
  const refreshFlow = useCallback(() => {
    if (!selectedProject || !selectedFlow) return;
    api.getFlow(selectedProject, selectedFlow).then((f) => {
      setFlow(f);
      setRfNodes(toReactFlowNodes(f));
      setRfEdges(toReactFlowEdges(f));
      setPendingOps([]);
      setDirty(false);
    }).catch((e) => setError(String(e)));
  }, [selectedProject, selectedFlow]);

  // --- React Flow callbacks ---

  const onNodeClick: NodeMouseHandler = useCallback((_, node) => {
    setSelectedNode(node);
  }, []);

  const onNodeDragStop: NodeMouseHandler = useCallback((_, node) => {
    // Record a moveNode op
    setPendingOps((prev) => [
      ...prev,
      { op: 'moveNode', nodeId: node.id, position: node.position },
    ]);
    setDirty(true);
  }, []);

  const onConnect = useCallback((conn: Connection) => {
    setRfEdges((eds) => rfAddEdge({ ...conn, animated: false }, eds));
    if (conn.source && conn.target) {
      setPendingOps((prev) => [
        ...prev,
        { op: 'addEdge', from: conn.source, to: conn.target },
      ]);
      setDirty(true);
    }
  }, []);

  const onNodesDelete: OnNodesDelete = useCallback((nodes: Node[]) => {
    for (const node of nodes) {
      setPendingOps((prev) => [...prev, { op: 'removeNode', nodeId: node.id }]);
    }
    if (nodes.length > 0) setDirty(true);
    setSelectedNode(null);
  }, []);

  const onEdgesDelete: OnEdgesDelete = useCallback((edges: Edge[]) => {
    for (const edge of edges) {
      if (edge.source && edge.target) {
        setPendingOps((prev) => [
          ...prev,
          { op: 'removeEdge', from: edge.source, to: edge.target },
        ]);
      }
    }
    if (edges.length > 0) setDirty(true);
  }, []);

  // --- Drag-and-drop from palette ---

  const onDragStart = (e: React.DragEvent, stepType: string) => {
    dragType.current = stepType;
    e.dataTransfer.effectAllowed = 'move';
  };

  const onDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
  };

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    const stepType = dragType.current;
    dragType.current = null;
    if (!stepType || !flow) return;

    const position = {
      x: e.clientX - 300, // approximate offset for left sidebar
      y: e.clientY - 50,  // approximate offset for header
    };

    const nodeId = genNodeId(stepType);
    const paletteEntry = PALETTE_STEPS.find((s) => s.type === stepType);
    const fidelity = paletteEntry?.fidelity || 'simulated';

    const newNode: Node = {
      id: nodeId,
      type: 'default',
      position,
      data: {
        label: nodeId,
        stepType,
        fidelity,
        config: {},
      },
      className: `oiw-node oiw-node--${stepType.replace(/\./g, '-')}`,
    };

    setRfNodes((nds) => [...nds, newNode]);
    setPendingOps((prev) => [
      ...prev,
      {
        op: 'addNode',
        node: { id: nodeId, type: stepType, config: {}, fidelity },
        position,
      },
    ]);
    setDirty(true);
    setSelectedNode(newNode);
  };

  // --- Save (PATCH) ---

  const save = async () => {
    if (!selectedProject || !selectedFlow || pendingOps.length === 0) return;
    setLoading(true);
    setError(null);
    try {
      await api.patchFlow(selectedProject, selectedFlow, pendingOps, gitStatus?.head_sha || undefined);
      // Reload the flow to get the server's canonical view
      const f = await api.getFlow(selectedProject, selectedFlow);
      setFlow(f);
      setRfNodes(toReactFlowNodes(f));
      setRfEdges(toReactFlowEdges(f));
      setPendingOps([]);
      setDirty(false);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  };

  // --- Properties panel editing ---

  const updateNodeConfig = (nodeId: string, key: string, value: string) => {
    // Update local RF state
    setRfNodes((nds) =>
      nds.map((n) => {
        if (n.id !== nodeId) return n;
        const config = { ...(n.data as { config?: Record<string, unknown> }).config };
        config[key] = value;
        return { ...n, data: { ...n.data, config } };
      })
    );
    // Update selected node if it's the one being edited
    setSelectedNode((prev) => {
      if (!prev || prev.id !== nodeId) return prev;
      const config = { ...(prev.data as { config?: Record<string, unknown> }).config };
      config[key] = value;
      return { ...prev, data: { ...prev.data, config } };
    });
    // Queue patch op
    setPendingOps((prev) => [
      ...prev,
      { op: 'updateNodeConfig', nodeId, config: { [key]: value } },
    ]);
    setDirty(true);
  };

  const updateNodeId = (nodeId: string, newId: string) => {
    setRfNodes((nds) =>
      nds.map((n) => (n.id === nodeId ? { ...n, id: newId, data: { ...n.data, label: newId } } : n))
    );
    setSelectedNode((prev) => (prev && prev.id === nodeId ? { ...prev, id: newId, data: { ...prev.data, label: newId } } : prev));
  };

  // --- Action buttons ---

  const runValidate = async () => {
    if (!selectedProject) return;
    setLoading(true);
    setError(null);
    try {
      const result = await api.validate(selectedProject, true);
      setValidation(result);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  };

  const runTests = async () => {
    if (!selectedProject) return;
    setLoading(true);
    setError(null);
    try {
      const result = await api.runTests(selectedProject, selectedFlow ?? undefined);
      setTests(result);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  };

  const runBuild = async () => {
    if (!selectedProject) return;
    setLoading(true);
    setError(null);
    try {
      const result = await api.build(selectedProject, 'sap-cloud-integration-2026-07');
      setBuild(result);
      const gs = await api.gitStatus(selectedProject);
      setGitStatus(gs);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  };

  const loadGitStatus = async () => {
    if (!selectedProject) return;
    try {
      const gs = await api.gitStatus(selectedProject);
      setGitStatus(gs);
    } catch (e) {
      setError(String(e));
    }
  };

  const viewDiff = async () => {
    if (!selectedProject) return;
    setLoading(true);
    setError(null);
    try {
      const result = await api.getDiff(selectedProject, 'HEAD~1');
      setDiff(result);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  };

  const runSimulation = async () => {
    if (!selectedProject || !selectedFlow) return;
    setSimulating(true);
    setError(null);
    setSimulation(null);
    try {
      const result = await api.simulate(selectedProject, selectedFlow, {
        body_inline: '{"orderId":"ORD-001","customerId":"CUST-42","region":"EU","items":[{"sku":"SKU-A","quantity":2}]}',
        headers: { 'Content-Type': 'application/json' },
        mocks: [
          { target: 'receiver-s4-eu', respond: { status: 201, body: '{"id":"4711"}' } },
        ],
      });
      setSimulation(result);
    } catch (e) {
      setError(String(e));
    } finally {
      setSimulating(false);
    }
  };

  return (
    <div className="app">
      <header className="app__header">
        <div className="app__brand">
          <span className="app__logo">OIW</span>
          <span className="app__title">Open Integration Workbench</span>
        </div>
        <div className="app__header-actions">
          {dirty && (
            <span className="badge badge--warn">unsaved changes ({pendingOps.length})</span>
          )}
          {dirty && (
            <button onClick={save} disabled={loading} className="btn btn--primary btn--sm">
              Save
            </button>
          )}
          {gitStatus && (
            <div className="app__git-status">
              <span className="badge badge--info">{gitStatus.branch}</span>
              <span className="badge badge--mono">{gitStatus.head_sha}</span>
              {gitStatus.dirty && <span className="badge badge--warn">dirty</span>}
              {gitStatus.last_build_digest && (
                <span className="badge badge--success badge--mono">
                  build: {gitStatus.last_build_digest.substring(7, 14)}
                </span>
              )}
            </div>
          )}
        </div>
      </header>

      <div className="app__body">
        <aside className="sidebar sidebar--left">
          <div className="sidebar__section">
            <h3 className="sidebar__title">Projects</h3>
            <ul className="project-list">
              {projects.map((p) => (
                <li
                  key={p.id}
                  className={`project-list__item ${selectedProject === p.id ? 'project-list__item--active' : ''}`}
                  onClick={() => setSelectedProject(p.id)}
                >
                  <div className="project-list__name">{p.name}</div>
                  <div className="project-list__meta">
                    {p.flow_count} flow(s) · {p.test_count} test(s)
                  </div>
                </li>
              ))}
            </ul>
          </div>

          {flows.length > 0 && (
            <div className="sidebar__section">
              <h3 className="sidebar__title">Flows</h3>
              <ul className="project-list">
                {flows.map((f) => (
                  <li
                    key={f.id}
                    className={`project-list__item ${selectedFlow === f.id ? 'project-list__item--active' : ''}`}
                    onClick={() => setSelectedFlow(f.id)}
                  >
                    <div className="project-list__name">{f.name}</div>
                    <div className="project-list__meta">
                      v{f.version} · {f.node_count} node(s)
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {flow && (
            <div className="sidebar__section">
              <h3 className="sidebar__title">Palette</h3>
              <p className="palette__hint">Drag onto canvas</p>
              <div className="palette">
                {PALETTE_STEPS.map((step) => (
                  <div
                    key={step.type}
                    className="palette__item"
                    draggable
                    onDragStart={(e) => onDragStart(e, step.type)}
                  >
                    <span
                      className="palette__dot"
                      style={{ background: fidelityColor(step.fidelity) }}
                    />
                    <span className="palette__name">{step.name}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {resources.length > 0 && (
            <div className="sidebar__section">
              <h3 className="sidebar__title">Resources</h3>
              <ul className="resource-list">
                {resources.map((res) => (
                  <li
                    key={res.path}
                    className={`resource-list__item ${selectedResource?.path === res.path ? 'resource-list__item--active' : ''}`}
                    onClick={() => {
                      setSelectedResource(res);
                      setViewMode('resource');
                    }}
                  >
                    <div className="resource-list__name">{res.name}</div>
                    <div className="resource-list__meta">
                      <span className="badge badge--mono">{res.language}</span>
                      <span className="resource-list__size">{res.size}B</span>
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {selectedProject && (
            <div className="sidebar__section">
              <h3 className="sidebar__title">Actions</h3>
              <div className="action-buttons">
                <button onClick={runValidate} disabled={loading} className="btn btn--primary">
                  Validate
                </button>
                <button onClick={runTests} disabled={loading} className="btn btn--primary">
                  Run Tests
                </button>
                <button onClick={runBuild} disabled={loading} className="btn btn--primary">
                  Build
                </button>
                <button onClick={runSimulation} disabled={simulating || !selectedFlow} className="btn btn--primary">
                  {simulating ? 'Simulating…' : 'Simulate'}
                </button>
                <button onClick={viewDiff} disabled={loading} className="btn btn--secondary">
                  View Diff
                </button>
                <button onClick={loadGitStatus} disabled={loading} className="btn btn--secondary">
                  Git Status
                </button>
              </div>
            </div>
          )}
        </aside>

        <main className="canvas-area">
          {error && (
            <div className="error-banner">
              {error}
              <button onClick={() => setError(null)}>×</button>
            </div>
          )}
          {loading && <div className="loading-overlay">Loading…</div>}
          {viewMode === 'resource' && selectedResource && selectedProject ? (
            <ResourceEditor
              projectId={selectedProject}
              resource={selectedResource}
              onClose={() => {
                setSelectedResource(null);
                setViewMode('canvas');
              }}
            />
          ) : flow ? (
            <>
              <div className="canvas-toolbar">
                <button
                  className={`canvas-tab ${viewMode === 'canvas' ? 'canvas-tab--active' : ''}`}
                  onClick={() => setViewMode('canvas')}
                >
                  Flow Canvas
                </button>
                {selectedResource && (
                  <button
                    className={`canvas-tab ${viewMode === 'resource' ? 'canvas-tab--active' : ''}`}
                    onClick={() => setViewMode('resource')}
                  >
                    {selectedResource.name}
                  </button>
                )}
              </div>
              <div className="canvas-container" onDragOver={onDragOver} onDrop={onDrop}>
                <ReactFlow
                  nodes={rfNodes}
                  edges={rfEdges}
                  onNodeClick={onNodeClick}
                  onNodeDragStop={onNodeDragStop}
                  onConnect={onConnect}
                  onNodesDelete={onNodesDelete}
                  onEdgesDelete={onEdgesDelete}
                  deleteKeyCode={['Delete', 'Backspace']}
                  fitView
                  attributionPosition="bottom-left"
                >
                  <Background color="#2e3344" gap={20} />
                  <Controls />
                  <MiniMap
                    nodeColor={(n) => fidelityColor((n.data as { fidelity?: string })?.fidelity ?? '')}
                    maskColor="rgba(15, 17, 23, 0.8)"
                  />
                </ReactFlow>
              </div>
            </>
          ) : (
            <div className="canvas-placeholder">
              <p>Select a project and flow to view the integration graph.</p>
            </div>
          )}
        </main>

        <aside className="sidebar sidebar--right">
          {/* WP-04 Task 9: Co-Pilot panel (LLM-driven agent interface) */}
          <div className="sidebar__section sidebar__section--copilot">
            <CoPilotPanel
              projectId={selectedProject}
              flowId={selectedFlow}
              onApplied={refreshFlow}
            />
          </div>
          {selectedNode && (
            <div className="sidebar__section">
              <h3 className="sidebar__title">Node Properties</h3>
              <div className="properties">
                <div className="properties__row">
                  <span className="properties__label">ID</span>
                  <input
                    className="properties__input"
                    value={selectedNode.id}
                    onChange={(e) => updateNodeId(selectedNode.id, e.target.value)}
                  />
                </div>
                <div className="properties__row">
                  <span className="properties__label">Type</span>
                  <span className="properties__value">
                    {(selectedNode.data as { stepType?: string }).stepType}
                  </span>
                </div>
                <div className="properties__row">
                  <span className="properties__label">Fidelity</span>
                  <span
                    className="properties__value"
                    style={{
                      color: fidelityColor((selectedNode.data as { fidelity?: string }).fidelity ?? ''),
                    }}
                  >
                    {(selectedNode.data as { fidelity?: string }).fidelity}
                  </span>
                </div>
                <div className="properties__row properties__row--config">
                  <span className="properties__label">Config</span>
                  <ConfigEditor
                    nodeId={selectedNode.id}
                    config={(selectedNode.data as { config?: Record<string, unknown> }).config || {}}
                    onChange={updateNodeConfig}
                  />
                </div>
              </div>
            </div>
          )}

          {validation && (
            <div className="sidebar__section">
              <h3 className="sidebar__title">
                Validation
                <span className={`badge ${validation.passed ? 'badge--success' : 'badge--error'}`}>
                  {validation.passed ? 'PASS' : 'FAIL'}
                </span>
              </h3>
              <div className="validation-results">
                {validation.errors.length === 0 && validation.warnings.length === 0 ? (
                  <p className="muted">No issues found.</p>
                ) : (
                  <>
                    {validation.errors.map((e, i) => (
                      <div key={`e${i}`} className="validation-item validation-item--error">
                        {e}
                      </div>
                    ))}
                    {validation.warnings.map((w, i) => (
                      <div key={`w${i}`} className="validation-item validation-item--warn">
                        {w}
                      </div>
                    ))}
                  </>
                )}
              </div>
            </div>
          )}

          {tests && (
            <div className="sidebar__section">
              <h3 className="sidebar__title">Test Results</h3>
              <div className="test-results">
                {tests.map((t, i) => (
                  <div
                    key={i}
                    className={`test-result ${t.passed ? 'test-result--pass' : 'test-result--fail'}`}
                  >
                    <div className="test-result__header">
                      <span className="test-result__symbol">{t.passed ? '✓' : '✗'}</span>
                      <span className="test-result__name">{t.test_name}</span>
                      <span className="test-result__time">{t.duration_ms}ms</span>
                    </div>
                    {!t.passed && (
                      <ul className="test-result__failures">
                        {t.failures.map((f, j) => (
                          <li key={j}>{f}</li>
                        ))}
                      </ul>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {build && (
            <div className="sidebar__section">
              <h3 className="sidebar__title">Build Result</h3>
              <div className="build-result">
                <div className="properties__row">
                  <span className="properties__label">Digest</span>
                  <span className="properties__value properties__value--mono">{build.digest}</span>
                </div>
                <div className="properties__row">
                  <span className="properties__label">Target</span>
                  <span className="properties__value">{build.target_profile}</span>
                </div>
                <div className="properties__row">
                  <span className="properties__label">Compiler</span>
                  <span className="properties__value">{build.compiler_version}</span>
                </div>
                <div className="properties__row">
                  <span className="properties__label">Entries</span>
                  <span className="properties__value">{build.entry_count}</span>
                </div>
              </div>
            </div>
          )}

          {diff && (
            <div className="sidebar__section">
              <h3 className="sidebar__title">
                Semantic Diff
                <span className="badge badge--mono">{diff.total_changes}</span>
              </h3>
              <DiffViewer diff={diff} />
            </div>
          )}

          {simulation && (
            <div className="sidebar__section">
              <h3 className="sidebar__title">
                Simulation Trace
                <span className={`badge ${simulation.status === 'COMPLETED' ? 'badge--success' : 'badge--error'}`}>
                  {simulation.status}
                </span>
                <span className="badge badge--mono">{simulation.duration_ms}ms</span>
              </h3>
              <div className="trace-list">
                {simulation.trace.map((t: TraceEntry, i: number) => (
                  <div key={i} className={`trace-item trace-item--${t.direction}`}>
                    <span className="trace-item__node">{t.node_id}</span>
                    <span className="trace-item__direction">{t.direction}</span>
                    <span className="trace-item__summary">{t.summary}</span>
                  </div>
                ))}
              </div>
              {simulation.outbound_calls.length > 0 && (
                <div className="outbound-calls">
                  <span className="properties__label">Outbound calls</span>
                  {simulation.outbound_calls.map((c, i) => (
                    <div key={i} className="outbound-call">
                      <span className="outbound-call__target">{c.target}</span>
                      <span className="outbound-call__method">{c.method}</span>
                      <span className="outbound-call__url">{c.url}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}

/** Inline config editor — renders each key as a label + text input. */
function ConfigEditor({
  nodeId,
  config,
  onChange,
}: {
  nodeId: string;
  config: Record<string, unknown>;
  onChange: (nodeId: string, key: string, value: string) => void;
}) {
  const keys = Object.keys(config);
  if (keys.length === 0) {
    return <p className="muted">No config. Add keys via YAML or the API.</p>;
  }
  return (
    <div className="config-editor">
      {keys.map((key) => {
        const value = config[key];
        const strValue = typeof value === 'object' ? JSON.stringify(value) : String(value ?? '');
        return (
          <div key={key} className="config-editor__row">
            <label className="config-editor__label">{key}</label>
            <input
              className="config-editor__input"
              value={strValue}
              onChange={(e) => onChange(nodeId, key, e.target.value)}
            />
          </div>
        );
      })}
    </div>
  );
}

export default App;
