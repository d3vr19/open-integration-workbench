import { useCallback, useState, useEffect, useRef } from 'react';
import type { Connection, Edge, Node, NodeMouseHandler, OnNodesDelete, OnEdgesDelete } from 'reactflow';
import './App.css';

import { api } from './api';
import type { ProjectSummary, FlowSummary, IntegrationFlow, ValidationResult, TestResult, BuildResult, GitStatus, SimulationResult, TraceEntry, ResourceSummary, StructuredDiff, EmgHit } from './api';
import { toReactFlowNodes, toReactFlowEdges } from './flow-utils';
import { ResourceEditor } from './ResourceEditor';
import { DiffViewer } from './DiffViewer';
import { CoPilotPanel } from './components/llm/CoPilotPanel';
import { EmgInsightPanel } from './components/emg/EmgInsightPanel';
import { DeployPanel } from './components/deploy/DeployPanel';
import { PalettePanel } from './components/canvas/PalettePanel';
import { FlowCanvas } from './components/canvas/FlowCanvas';
import { PropertiesPanel } from './components/canvas/PropertiesPanel';
import { TraceInspector } from './components/canvas/TraceInspector';

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
  // WP-08 PR-10 / OW-032: truthful EMG retrieval metadata from the last
  // co-pilot round-trip. The ⚡ badge renders from this — never hardcoded.
  const [lastEmgHit, setLastEmgHit] = useState<EmgHit | null>(null);
  const [validation, setValidation] = useState<ValidationResult | null>(null);
  const [tests, setTests] = useState<TestResult[] | null>(null);
  const [build, setBuild] = useState<BuildResult | null>(null);
  const [gitStatus, setGitStatus] = useState<GitStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pendingOps, setPendingOps] = useState<unknown[]>([]);
  const [dirty, setDirty] = useState(false);
  const [simulation, setSimulation] = useState<SimulationResult | null>(null);
  const [showRawTrace, setShowRawTrace] = useState(false);
  const [simulating, setSimulating] = useState(false);
  const [resources, setResources] = useState<ResourceSummary[]>([]);
  const [selectedResource, setSelectedResource] = useState<ResourceSummary | null>(null);
  const [viewMode, setViewMode] = useState<'canvas' | 'resource'>('canvas');
  const [diff, setDiff] = useState<StructuredDiff | null>(null);
  const dragType = useRef<string | null>(null);

  useEffect(() => {
    api.listProjects().then(setProjects).catch((e) => setError(String(e)));
  }, []);

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

  const onNodeClick: NodeMouseHandler = useCallback((_, node) => {
    setSelectedNode(node);
  }, []);

  const onNodeDragStop: NodeMouseHandler = useCallback((_, node) => {
    setRfNodes((nds) => nds.map((n) => (n.id === node.id ? node : n)));
  }, []);

  const onConnect = useCallback((connection: Connection) => {
    const source = connection.source;
    const target = connection.target;
    if (!source || !target) return;
    setRfEdges((eds) => [...eds, { id: `${source}-${target}`, source, target }]);
    setPendingOps((ops) => [...ops, { op: 'addEdge', from: source, to: target }]);
    setDirty(true);
  }, []);

  const onNodesDelete: OnNodesDelete = useCallback((nodes) => {
    const ids = new Set(nodes.map((n) => n.id));
    setRfNodes((nds) => nds.filter((n) => !ids.has(n.id)));
    setRfEdges((eds) => eds.filter((e) => !ids.has(e.source) && !ids.has(e.target)));
    setPendingOps((ops) => [...ops, ...nodes.map((n) => ({ op: 'removeNode', nodeId: n.id }))]);
    setDirty(true);
  }, []);

  const onEdgesDelete: OnEdgesDelete = useCallback((edges) => {
    const keys = new Set(edges.map((e) => `${e.source}-${e.target}`));
    setRfEdges((eds) => eds.filter((e) => !keys.has(`${e.source}-${e.target}`)));
    setPendingOps((ops) => [...ops, ...edges.map((e) => ({ op: 'removeEdge', from: e.source, to: e.target }))]);
    setDirty(true);
  }, []);

  const onDragStart = useCallback((e: React.DragEvent, stepType: string) => {
    dragType.current = stepType;
    e.dataTransfer.effectAllowed = 'move';
  }, []);

  const onDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
  }, []);

  const onDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    const stepType = dragType.current;
    if (!stepType || !flow) return;
    const nodeId = genNodeId(stepType);
    const position = { x: e.clientX - 200, y: e.clientY - 100 };
    const newNode: Node = {
      id: nodeId,
      type: 'default',
      position,
      data: { label: stepType, stepType, fidelity: 'simulated', config: {} },
    };
    setRfNodes((nds) => [...nds, newNode]);
    setPendingOps((ops) => [...ops, { op: 'addNode', node: { id: nodeId, type: stepType, config: {}, fidelity: 'simulated' } }]);
    setDirty(true);
    dragType.current = null;
  }, [flow]);

  const updateNodeId = useCallback((oldId: string, newId: string) => {
    setRfNodes((nds) => nds.map((n) => (n.id === oldId ? { ...n, id: newId } : n)));
    setRfEdges((eds) => eds.map((e) => ({
      ...e,
      source: e.source === oldId ? newId : e.source,
      target: e.target === oldId ? newId : e.target,
    })));
    setSelectedNode((sn) => (sn && sn.id === oldId ? { ...sn, id: newId } : sn));
    setDirty(true);
  }, []);

  const updateNodeConfig = useCallback((nodeId: string, key: string, value: string) => {
    setRfNodes((nds) => nds.map((n) => {
      if (n.id !== nodeId) return n;
      const data = n.data as { config?: Record<string, unknown> };
      return { ...n, data: { ...data, config: { ...data.config, [key]: value } } };
    }));
    setDirty(true);
  }, []);

  const save = useCallback(async () => {
    if (!selectedProject || !selectedFlow || pendingOps.length === 0) return;
    setLoading(true);
    setError(null);
    try {
      const headResp = await fetch(`/api/v1/projects/${selectedProject}/git/status`).then((r) => r.json());
      const baseRevision = headResp.head_sha || 'unknown';
      await api.patchFlow(selectedProject, selectedFlow, pendingOps as unknown[], baseRevision);
      setPendingOps([]);
      setDirty(false);
      await refreshFlow();
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, [selectedProject, selectedFlow, pendingOps, refreshFlow]);

  const runValidate = useCallback(async () => {
    if (!selectedProject) return;
    setLoading(true);
    setError(null);
    try {
      const result = await api.validate(selectedProject);
      setValidation(result);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, [selectedProject]);

  const runTests = useCallback(async () => {
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
  }, [selectedProject, selectedFlow]);

  const runBuild = useCallback(async () => {
    if (!selectedProject) return;
    setLoading(true);
    setError(null);
    try {
      const result = await api.build(selectedProject, 'sap-cloud-integration-2026-07');
      setBuild(result);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, [selectedProject]);

  const runSimulation = useCallback(async () => {
    if (!selectedProject || !selectedFlow) return;
    setSimulating(true);
    setError(null);
    try {
      const result = await api.simulate(selectedProject, selectedFlow, { body_inline: '{}' });
      setSimulation(result);
    } catch (e) {
      setError(String(e));
    } finally {
      setSimulating(false);
    }
  }, [selectedProject, selectedFlow]);

  const viewDiff = useCallback(async () => {
    if (!selectedProject) return;
    setLoading(true);
    try {
      const result = await api.getDiff(selectedProject);
      setDiff(result);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, [selectedProject]);

  const loadGitStatus = useCallback(async () => {
    if (!selectedProject) return;
    setLoading(true);
    try {
      const result = await api.gitStatus(selectedProject);
      setGitStatus(result);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, [selectedProject]);

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
                  {gitStatus.last_build_digest.slice(0, 12)}
                </span>
              )}
            </div>
          )}
        </div>
      </header>

      <div className="app__body">
        {/* LEFT SIDEBAR: Projects, Flows, Palette, Resources, Actions */}
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
                    <span className="badge badge--mono">{p.flow_count} flows</span>
                    <span className="badge badge--mono">{p.test_count} tests</span>
                  </div>
                </li>
              ))}
            </ul>
          </div>

          {selectedProject && (
            <>
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
                        <span className="badge badge--mono">{f.node_count} nodes</span>
                      </div>
                    </li>
                  ))}
                </ul>
              </div>

              <PalettePanel onDragStart={onDragStart} visible={!!selectedFlow} />

              {resources.length > 0 && (
                <div className="sidebar__section">
                  <h3 className="sidebar__title">Resources</h3>
                  <ul className="resource-list">
                    {resources.map((res) => (
                      <li
                        key={res.path}
                        className={`resource-list__item ${selectedResource?.path === res.path ? 'resource-list__item--active' : ''}`}
                        onClick={() => { setSelectedResource(res); setViewMode('resource'); }}
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

              <div className="sidebar__section">
                <h3 className="sidebar__title">Actions</h3>
                <div className="action-buttons">
                  <button onClick={runValidate} disabled={loading} className="btn btn--primary">Validate</button>
                  <button onClick={runTests} disabled={loading} className="btn btn--primary">Run Tests</button>
                  <button onClick={runBuild} disabled={loading} className="btn btn--primary">Build</button>
                  <button onClick={runSimulation} disabled={simulating || !selectedFlow} className="btn btn--primary">
                    {simulating ? 'Simulating…' : 'Simulate'}
                  </button>
                  <button onClick={viewDiff} disabled={loading} className="btn btn--secondary">View Diff</button>
                  <button onClick={loadGitStatus} disabled={loading} className="btn btn--secondary">Git Status</button>
                </div>
              </div>
            </>
          )}
        </aside>

        {/* MAIN: Canvas area */}
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
              onClose={() => { setSelectedResource(null); setViewMode('canvas'); }}
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
              <FlowCanvas
                nodes={rfNodes}
                edges={rfEdges}
                onNodeClick={onNodeClick}
                onNodeDragStop={onNodeDragStop}
                onConnect={onConnect}
                onNodesDelete={onNodesDelete}
                onEdgesDelete={onEdgesDelete}
                onDragOver={onDragOver}
                onDrop={onDrop}
              />
            </>
          ) : (
            <div className="canvas-placeholder">
              <p>Select a project and flow to view the integration graph.</p>
            </div>
          )}
        </main>

        {/* RIGHT SIDEBAR: Co-Pilot, Properties, Validation, Tests, Build, Diff, Simulation */}
        <aside className="sidebar sidebar--right">
          <div className="sidebar__section sidebar__section--copilot">
            <CoPilotPanel
              projectId={selectedProject}
              flowId={selectedFlow}
              onApplied={refreshFlow}
              onEmgHit={setLastEmgHit}
            />
          </div>
          {/* WP-06 E-003: EMG Insight Panel — badge driven by real agent metadata */}
          <div className="sidebar__section">
            <EmgInsightPanel projectId={selectedProject} emgHit={lastEmgHit} />
          </div>
          {/* WP-06 E-002: Deploy Panel */}
          <div className="sidebar__section">
            <DeployPanel projectId={selectedProject} />
          </div>
          {selectedNode && (
            <PropertiesPanel
              selectedNode={selectedNode}
              onUpdateNodeId={updateNodeId}
              onUpdateNodeConfig={updateNodeConfig}
            />
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
                      <div key={`e${i}`} className="validation-item validation-item--error">{e}</div>
                    ))}
                    {validation.warnings.map((w, i) => (
                      <div key={`w${i}`} className="validation-item validation-item--warn">{w}</div>
                    ))}
                  </>
                )}
              </div>
            </div>
          )}
          {tests && (
            <div className="sidebar__section">
              <h3 className="sidebar__title">Tests</h3>
              {tests.map((t, i) => (
                <div key={i} className={`test-item ${t.passed ? 'test-item--pass' : 'test-item--fail'}`}>
                  <span className="test-item__name">{t.flow_id} :: {t.test_name}</span>
                  <span className="badge badge--mono">{t.duration_ms}ms</span>
                </div>
              ))}
            </div>
          )}
          {build && (
            <div className="sidebar__section">
              <h3 className="sidebar__title">Build</h3>
              <div className="build-result">
                <div><span className="properties__label">Digest:</span> {build.digest}</div>
                <div><span className="properties__label">Target:</span> {build.target_profile}</div>
                <div><span className="properties__label">Entries:</span> {build.entry_count}</div>
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
                <button
                  className="trace-inspector__raw-toggle"
                  onClick={() => setShowRawTrace((v) => !v)}
                  title="Toggle the raw event list"
                >
                  {showRawTrace ? 'step view' : 'raw events'}
                </button>
              </h3>
              {showRawTrace ? (
                <div className="trace-list">
                  {simulation.trace.map((t: TraceEntry, i: number) => (
                    <div key={i} className={`trace-item trace-item--${t.direction}`}>
                      <span className="trace-item__node">{t.node_id}</span>
                      <span className="trace-item__direction">{t.direction}</span>
                      <span className="trace-item__summary">{t.summary}</span>
                    </div>
                  ))}
                </div>
              ) : (
                <TraceInspector simulation={simulation} />
              )}
              {showRawTrace && simulation.outbound_calls.length > 0 && (
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

export default App;
