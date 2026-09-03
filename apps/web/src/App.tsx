import { useState } from 'react';
import './App.css';
import type { EmgHit } from './api';
import { useProjectWorkspace } from './hooks/useProjectWorkspace';
import { useFlowEditor } from './hooks/useFlowEditor';
import { useProjectActions } from './hooks/useProjectActions';
import { AppHeader } from './components/layout/AppHeader';
import { LeftSidebar } from './components/layout/LeftSidebar';
import { CanvasArea } from './components/layout/CanvasArea';
import { RightSidebar } from './components/layout/RightSidebar';

function App() {
  // WP-08 PR-10 / OW-032: truthful EMG retrieval metadata from the last
  // co-pilot round-trip. The ⚡ badge renders from this — never hardcoded.
  const [lastEmgHit, setLastEmgHit] = useState<EmgHit | null>(null);

  const workspace = useProjectWorkspace();
  const flowEditor = useFlowEditor(workspace.selectedProject, workspace.selectedFlow);
  const actions = useProjectActions(workspace.selectedProject, workspace.selectedFlow);

  return (
    <div className="app">
      <AppHeader
        dirty={flowEditor.dirty}
        pendingOpsCount={flowEditor.pendingOps.length}
        loading={flowEditor.flowLoading || actions.actionLoading}
        onSave={flowEditor.save}
        gitStatus={actions.gitStatus}
      />

      <div className="app__body">
        <LeftSidebar
          projects={workspace.projects}
          selectedProject={workspace.selectedProject}
          onSelectProject={workspace.setSelectedProject}
          flows={workspace.flows}
          selectedFlow={workspace.selectedFlow}
          onSelectFlow={workspace.setSelectedFlow}
          resources={workspace.resources}
          selectedResource={workspace.selectedResource}
          onSelectResource={(res) => {
            workspace.setSelectedResource(res);
            workspace.setViewMode('resource');
          }}
          onDragStart={flowEditor.onDragStart}
          actionsLoading={actions.actionLoading}
          simulating={actions.simulating}
          onRunValidate={actions.runValidate}
          onRunTests={actions.runTests}
          onRunBuild={actions.runBuild}
          onRunSimulation={actions.runSimulation}
          onViewDiff={actions.viewDiff}
          onLoadGitStatus={actions.loadGitStatus}
          workspaceError={workspace.error}
          onClearWorkspaceError={() => workspace.setError(null)}
          actionError={actions.actionError}
          onClearActionError={() => actions.setActionError(null)}
        />

        <CanvasArea
          selectedProject={workspace.selectedProject}
          selectedResource={workspace.selectedResource}
          viewMode={workspace.viewMode}
          onCloseResource={() => {
            workspace.setSelectedResource(null);
            workspace.setViewMode('canvas');
          }}
          onSetViewMode={workspace.setViewMode}
          flow={flowEditor.flow}
          flowLoading={flowEditor.flowLoading}
          flowError={flowEditor.flowError}
          onClearFlowError={() => flowEditor.setFlowError(null)}
          rfNodes={flowEditor.rfNodes}
          rfEdges={flowEditor.rfEdges}
          onNodeClick={flowEditor.onNodeClick}
          onNodeDragStop={flowEditor.onNodeDragStop}
          onConnect={flowEditor.onConnect}
          onNodesDelete={flowEditor.onNodesDelete}
          onEdgesDelete={flowEditor.onEdgesDelete}
          onDragOver={flowEditor.onDragOver}
          onDrop={flowEditor.onDrop}
        />

        <RightSidebar
          selectedProject={workspace.selectedProject}
          selectedFlow={workspace.selectedFlow}
          onRefreshFlow={flowEditor.refreshFlow}
          lastEmgHit={lastEmgHit}
          onSetLastEmgHit={setLastEmgHit}
          selectedNode={flowEditor.selectedNode}
          onUpdateNodeId={flowEditor.updateNodeId}
          onUpdateNodeConfig={flowEditor.updateNodeConfig}
          validation={actions.validation}
          tests={actions.tests}
          build={actions.build}
          diff={actions.diff}
          simulation={actions.simulation}
          showRawTrace={actions.showRawTrace}
          onToggleRawTrace={() => actions.setShowRawTrace((v) => !v)}
        />
      </div>
    </div>
  );
}

export default App;
