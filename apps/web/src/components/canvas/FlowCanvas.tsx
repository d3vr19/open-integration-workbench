/**
 * FlowCanvas — ReactFlow wrapper with drag-and-drop (spec §10).
 *
 * Extracted from App.tsx as part of OW-029 (full SPA decomposition).
 * Renders the integration flow graph with node/edge manipulation,
 * drag-over/drop support for palette items, and minimap.
 */

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
}: FlowCanvasProps) {
  return (
    <div className="canvas-container" onDragOver={onDragOver} onDrop={onDrop}>
      <ReactFlow
        nodes={nodes}
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
