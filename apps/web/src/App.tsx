import { useCallback, useState, useEffect } from 'react';
import ReactFlow, {
  Background,
  Controls,
  MiniMap,
  type Node,
  type NodeMouseHandler,
} from 'reactflow';
import 'reactflow/dist/style.css';
import './App.css';

import { api } from './api';
import type { ProjectSummary, FlowSummary, IntegrationFlow, ValidationResult, TestResult, BuildResult, GitStatus } from './api';
import { toReactFlowNodes, toReactFlowEdges, fidelityColor } from './flow-utils';

function App() {
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [selectedProject, setSelectedProject] = useState<string | null>(null);
  const [flows, setFlows] = useState<FlowSummary[]>([]);
  const [selectedFlow, setSelectedFlow] = useState<string | null>(null);
  const [flow, setFlow] = useState<IntegrationFlow | null>(null);
  const [selectedNode, setSelectedNode] = useState<Node | null>(null);
  const [validation, setValidation] = useState<ValidationResult | null>(null);
  const [tests, setTests] = useState<TestResult[] | null>(null);
  const [build, setBuild] = useState<BuildResult | null>(null);
  const [gitStatus, setGitStatus] = useState<GitStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

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
    api.listFlows(selectedProject).then(setFlows).catch((e) => setError(String(e)));
  }, [selectedProject]);

  // Load flow when selected
  useEffect(() => {
    if (!selectedProject || !selectedFlow) return;
    setFlow(null);
    setSelectedNode(null);
    api.getFlow(selectedProject, selectedFlow).then(setFlow).catch((e) => setError(String(e)));
  }, [selectedProject, selectedFlow]);

  const onNodeClick: NodeMouseHandler = useCallback((_, node) => {
    setSelectedNode(node);
  }, []);

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
      // Also refresh git status to show the new build digest
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

  const rfNodes = flow ? toReactFlowNodes(flow) : [];
  const rfEdges = flow ? toReactFlowEdges(flow) : [];

  return (
    <div className="app">
      {/* Top bar */}
      <header className="app__header">
        <div className="app__brand">
          <span className="app__logo">OIW</span>
          <span className="app__title">Open Integration Workbench</span>
        </div>
        <div className="app__header-actions">
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

      {/* Three-pane layout */}
      <div className="app__body">
        {/* Left sidebar — project explorer */}
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
                <button onClick={loadGitStatus} disabled={loading} className="btn btn--secondary">
                  Git Status
                </button>
              </div>
            </div>
          )}
        </aside>

        {/* Center — flow canvas */}
        <main className="canvas-area">
          {error && (
            <div className="error-banner">
              {error}
              <button onClick={() => setError(null)}>×</button>
            </div>
          )}
          {loading && <div className="loading-overlay">Loading…</div>}
          {flow ? (
            <ReactFlow
              nodes={rfNodes}
              edges={rfEdges}
              onNodeClick={onNodeClick}
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
          ) : (
            <div className="canvas-placeholder">
              <p>Select a project and flow to view the integration graph.</p>
            </div>
          )}
        </main>

        {/* Right sidebar — properties + results */}
        <aside className="sidebar sidebar--right">
          {selectedNode && (
            <div className="sidebar__section">
              <h3 className="sidebar__title">Node Properties</h3>
              <div className="properties">
                <div className="properties__row">
                  <span className="properties__label">ID</span>
                  <span className="properties__value">{selectedNode.id}</span>
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
                  <pre className="properties__code">
                    {JSON.stringify((selectedNode.data as { config?: unknown }).config, null, 2)}
                  </pre>
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
        </aside>
      </div>
    </div>
  );
}

export default App;
