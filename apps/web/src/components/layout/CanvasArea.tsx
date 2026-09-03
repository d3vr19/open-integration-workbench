import type React from 'react';
import type { Connection, Edge, Node, NodeMouseHandler, OnNodesDelete, OnEdgesDelete } from 'reactflow';
import type { IntegrationFlow, ResourceSummary } from '../../api';
import { FlowCanvas, type TraceBadgeData } from '../canvas/FlowCanvas';
import { ResourceEditor } from '../../ResourceEditor';

interface CanvasAreaProps {
  selectedProject: string | null;
  selectedResource: ResourceSummary | null;
  viewMode: 'canvas' | 'resource';
  onCloseResource: () => void;
  onSetViewMode: (mode: 'canvas' | 'resource') => void;
  flow: IntegrationFlow | null;
  flowLoading: boolean;
  flowError: string | null;
  onClearFlowError: () => void;
  rfNodes: Node[];
  rfEdges: Edge[];
  onNodeClick: NodeMouseHandler;
  onNodeDragStop: NodeMouseHandler;
  onConnect: (connection: Connection) => void;
  onNodesDelete: OnNodesDelete;
  onEdgesDelete: OnEdgesDelete;
  onDragOver: (e: React.DragEvent) => void;
  onDrop: (e: React.DragEvent) => void;
  traceBadges?: Map<string, TraceBadgeData>;
  selectedTraceNodeId?: string | null;
  onSelectTraceNode?: (nodeId: string) => void;
}

export function CanvasArea({
  selectedProject,
  selectedResource,
  viewMode,
  onCloseResource,
  onSetViewMode,
  flow,
  flowLoading,
  flowError,
  onClearFlowError,
  rfNodes,
  rfEdges,
  onNodeClick,
  onNodeDragStop,
  onConnect,
  onNodesDelete,
  onEdgesDelete,
  onDragOver,
  onDrop,
  traceBadges,
  selectedTraceNodeId,
  onSelectTraceNode,
}: CanvasAreaProps) {
  return (
    <main className="canvas-area">
      {flowError && (
        <div className="error-banner error-banner--inline">
          {flowError}
          <button onClick={onClearFlowError}>×</button>
        </div>
      )}
      {flowLoading && <div className="loading-overlay">Loading…</div>}
      {viewMode === 'resource' && selectedResource && selectedProject ? (
        <ResourceEditor
          projectId={selectedProject}
          resource={selectedResource}
          onClose={onCloseResource}
        />
      ) : flow ? (
        <>
          <div className="canvas-toolbar">
            <button
              className={`canvas-tab ${viewMode === 'canvas' ? 'canvas-tab--active' : ''}`}
              onClick={() => onSetViewMode('canvas')}
            >
              Flow Canvas
            </button>
            {selectedResource && (
              <button
                className={`canvas-tab ${viewMode === 'resource' ? 'canvas-tab--active' : ''}`}
                onClick={() => onSetViewMode('resource')}
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
            traceBadges={traceBadges}
            selectedTraceNodeId={selectedTraceNodeId}
            onSelectTraceNode={onSelectTraceNode}
          />
        </>
      ) : (
        <div className="canvas-placeholder">
          <p>Select a project and flow to view the integration graph.</p>
        </div>
      )}
    </main>
  );
}
