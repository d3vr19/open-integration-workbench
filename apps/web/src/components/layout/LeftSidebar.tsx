import type React from 'react';
import type { ProjectSummary, FlowSummary, ResourceSummary } from '../../api';
import { PalettePanel } from '../canvas/PalettePanel';

interface LeftSidebarProps {
  projects: ProjectSummary[];
  selectedProject: string | null;
  onSelectProject: (id: string) => void;
  flows: FlowSummary[];
  selectedFlow: string | null;
  onSelectFlow: (id: string) => void;
  resources: ResourceSummary[];
  selectedResource: ResourceSummary | null;
  onSelectResource: (res: ResourceSummary) => void;
  onDragStart: (e: React.DragEvent, stepType: string) => void;
  actionsLoading: boolean;
  simulating: boolean;
  onRunValidate: () => void;
  onRunTests: () => void;
  onRunBuild: () => void;
  onRunSimulation: () => void;
  onViewDiff: () => void;
  onLoadGitStatus: () => void;
  workspaceError: string | null;
  onClearWorkspaceError: () => void;
  actionError: string | null;
  onClearActionError: () => void;
}

export function LeftSidebar({
  projects,
  selectedProject,
  onSelectProject,
  flows,
  selectedFlow,
  onSelectFlow,
  resources,
  selectedResource,
  onSelectResource,
  onDragStart,
  actionsLoading,
  simulating,
  onRunValidate,
  onRunTests,
  onRunBuild,
  onRunSimulation,
  onViewDiff,
  onLoadGitStatus,
  workspaceError,
  onClearWorkspaceError,
  actionError,
  onClearActionError,
}: LeftSidebarProps) {
  return (
    <aside className="sidebar sidebar--left">
      {workspaceError && (
        <div className="error-banner error-banner--inline">
          {workspaceError}
          <button onClick={onClearWorkspaceError}>×</button>
        </div>
      )}

      <div className="sidebar__section">
        <h3 className="sidebar__title">Projects</h3>
        <ul className="project-list">
          {projects.map((p) => (
            <li
              key={p.id}
              className={`project-list__item ${selectedProject === p.id ? 'project-list__item--active' : ''}`}
              onClick={() => onSelectProject(p.id)}
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
                  onClick={() => onSelectFlow(f.id)}
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
                    onClick={() => onSelectResource(res)}
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
            {actionError && (
              <div className="error-banner error-banner--inline">
                {actionError}
                <button onClick={onClearActionError}>×</button>
              </div>
            )}
            <div className="action-buttons">
              <button onClick={onRunValidate} disabled={actionsLoading} className="btn btn--primary">
                Validate
              </button>
              <button onClick={onRunTests} disabled={actionsLoading} className="btn btn--primary">
                Run Tests
              </button>
              <button onClick={onRunBuild} disabled={actionsLoading} className="btn btn--primary">
                Build
              </button>
              <button
                onClick={onRunSimulation}
                disabled={simulating || !selectedFlow}
                className="btn btn--primary"
              >
                {simulating ? 'Simulating…' : 'Simulate'}
              </button>
              <button onClick={onViewDiff} disabled={actionsLoading} className="btn btn--secondary">
                View Diff
              </button>
              <button onClick={onLoadGitStatus} disabled={actionsLoading} className="btn btn--secondary">
                Git Status
              </button>
            </div>
          </div>
        </>
      )}
    </aside>
  );
}
