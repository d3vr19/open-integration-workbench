/**
 * FlowCanvas — ReactFlow wrapper with drag-and-drop (spec §10).
 *
 * Extracted from App.tsx as part of OW-029 (full SPA decomposition).
 * Renders the integration flow graph with node/edge manipulation,
 * drag-over/drop support for palette items, and minimap.
 *
 * WP-09 B-001: Canvas node badges wired to trace inspector.
 */

import { useMemo } from 'react';
import ReactFlow, {
  Background,
  Controls,
  MiniMap,
  type Connection,
  type Edge,
  type Node,
  type NodeMouseHandler,
  type OnNodesDelete,
  type OnEdgesDelete,
} from 'reactflow';
import 'reactflow/dist/style.css';

import { fidelityColor } from '../../flow-utils';

export interface TraceBadgeData {
  status: 'pass' | 'fail';
  durationMs: number | null;
}

interface FlowCanvasProps {
  nodes: Node[];
  edges: Edge[];
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

export function FlowCanvas({
  nodes,
  edges,
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
}: FlowCanvasProps) {
  const displayNodes = useMemo(() => {
    if (!traceBadges || traceBadges.size === 0) return nodes;

    return nodes.map((n) => {
      const badge = traceBadges.get(n.id);
      if (!badge) return n;

      const isActive = selectedTraceNodeId === n.id;
      const originalLabel =
        (n.data as { rawLabel?: string })?.rawLabel ??
        (typeof (n.data as { label?: unknown })?.label === 'string'
          ? (n.data as { label: string }).label
          : n.id);

      return {
        ...n,
        className: `${n.className ?? ''} oiw-node--traced oiw-node--trace-${badge.status} ${isActive ? 'oiw-node--trace-active' : ''}`.trim(),
        data: {
          ...n.data,
          rawLabel: originalLabel,
          label: (
            <div className="oiw-node-inner">
              <span className="oiw-node-label">{originalLabel}</span>
              <div
                className={`node-trace-badge node-trace-badge--${badge.status} ${isActive ? 'node-trace-badge--active' : ''}`}
                onClick={(e) => {
                  e.stopPropagation();
                  onSelectTraceNode?.(n.id);
                }}
                data-testid={`trace-badge-${n.id}`}
                title={`Simulation: ${badge.status.toUpperCase()}${badge.durationMs != null ? ` (${badge.durationMs}ms)` : ''} — click to inspect`}
              >
                <span className="node-trace-badge__icon">
                  {badge.status === 'pass' ? '✓' : '✖'}
                </span>
                {badge.durationMs != null && (
                  <span className="node-trace-badge__ms">{badge.durationMs}ms</span>
                )}
              </div>
            </div>
          ),
        },
      };
    });
  }, [nodes, traceBadges, selectedTraceNodeId, onSelectTraceNode]);

  return (
    <div className="canvas-container" onDragOver={onDragOver} onDrop={onDrop}>
      <ReactFlow
        nodes={displayNodes}
        edges={edges}
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
  );
}
