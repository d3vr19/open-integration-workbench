import type { Node } from 'reactflow';
import type { EmgHit, ValidationResult, TestResult, BuildResult, StructuredDiff, SimulationResult, TraceEntry } from '../../api';
import { CoPilotPanel } from '../llm/CoPilotPanel';
import { EmgInsightPanel } from '../emg/EmgInsightPanel';
import { DeployPanel } from '../deploy/DeployPanel';
import { PropertiesPanel } from '../canvas/PropertiesPanel';
import { DiffViewer } from '../../DiffViewer';
import { TraceInspector } from '../canvas/TraceInspector';

interface RightSidebarProps {
  selectedProject: string | null;
  selectedFlow: string | null;
  onRefreshFlow: () => void;
  lastEmgHit: EmgHit | null;
  onSetLastEmgHit: (hit: EmgHit | null) => void;
  selectedNode: Node | null;
  onUpdateNodeId: (oldId: string, newId: string) => void;
  onUpdateNodeConfig: (nodeId: string, key: string, value: string) => void;
  validation: ValidationResult | null;
  tests: TestResult[] | null;
  build: BuildResult | null;
  diff: StructuredDiff | null;
  simulation: SimulationResult | null;
  showRawTrace: boolean;
  onToggleRawTrace: () => void;
  selectedTraceNodeId?: string | null;
  onSelectTraceNodeId?: (nodeId: string | null) => void;
}

export function RightSidebar({
  selectedProject,
  selectedFlow,
  onRefreshFlow,
  lastEmgHit,
  onSetLastEmgHit,
  selectedNode,
  onUpdateNodeId,
  onUpdateNodeConfig,
  validation,
  tests,
  build,
  diff,
  simulation,
  showRawTrace,
  onToggleRawTrace,
  selectedTraceNodeId,
  onSelectTraceNodeId,
}: RightSidebarProps) {
  return (
    <aside className="sidebar sidebar--right">
      <div className="sidebar__section sidebar__section--copilot">
        <CoPilotPanel
          projectId={selectedProject}
          flowId={selectedFlow}
          onApplied={onRefreshFlow}
          onEmgHit={onSetLastEmgHit}
        />
      </div>

      <div className="sidebar__section">
        <EmgInsightPanel projectId={selectedProject} emgHit={lastEmgHit} />
      </div>

      <div className="sidebar__section">
        <DeployPanel projectId={selectedProject} />
      </div>

      {selectedNode && (
        <PropertiesPanel
          selectedNode={selectedNode}
          onUpdateNodeId={onUpdateNodeId}
          onUpdateNodeConfig={onUpdateNodeConfig}
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
          <h3 className="sidebar__title">Tests</h3>
          {tests.map((t, i) => (
            <div key={i} className={`test-item ${t.passed ? 'test-item--pass' : 'test-item--fail'}`}>
              <span className="test-item__name">
                {t.flow_id} :: {t.test_name}
              </span>
              <span className="badge badge--mono">{t.duration_ms}ms</span>
            </div>
          ))}
        </div>
      )}

      {build && (
        <div className="sidebar__section">
          <h3 className="sidebar__title">Build</h3>
          <div className="build-result">
            <div>
              <span className="properties__label">Digest:</span> {build.digest}
            </div>
            <div>
              <span className="properties__label">Target:</span> {build.target_profile}
            </div>
            <div>
              <span className="properties__label">Entries:</span> {build.entry_count}
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
            <span
              className={`badge ${simulation.status === 'COMPLETED' ? 'badge--success' : 'badge--error'}`}
            >
              {simulation.status}
            </span>
            <span className="badge badge--mono">{simulation.duration_ms}ms</span>
            <button
              className="trace-inspector__raw-toggle"
              onClick={onToggleRawTrace}
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
            <TraceInspector
              simulation={simulation}
              selectedNodeId={selectedTraceNodeId}
              onSelectNodeId={onSelectTraceNodeId}
            />
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
  );
}
