/**
 * Convert OIW IR to React Flow nodes and edges.
 * Spec ref: §10 (Visual Designer), §7.3 rule 4 (layout separation).
 *
 * Uses diagram.json for positions; falls back to auto-layout if missing.
 */

import type { Edge, Node } from 'reactflow';
import type { FlowEdge, IntegrationFlow } from './api';

interface DiagramNode {
  id: string;
  position: { x: number; y: number };
  lane?: string;
}

export function toReactFlowNodes(flow: IntegrationFlow): Node[] {
  const diagramNodes: Record<string, DiagramNode> = {};
  if (flow.diagram?.nodes) {
    for (const dn of flow.diagram.nodes) {
      diagramNodes[dn.id] = dn;
    }
  }

  const allNodes = [...flow.spec.entrypoints, ...flow.spec.nodes];
  const result: Node[] = [];

  // Auto-layout fallback: simple left-to-right column placement
  let autoX = 0;
  const autoY = 200;

  for (const n of allNodes) {
    const dn = diagramNodes[n.id];
    const position = dn?.position ?? { x: autoX, y: autoY };
    if (!dn) autoX += 250;

    const isEntrypoint = flow.spec.entrypoints.some((e) => e.id === n.id);
    const isReceiver = n.type.startsWith('receiver.');
    const nodeType = isEntrypoint ? 'input' : isReceiver ? 'output' : 'default';

    result.push({
      id: n.id,
      type: nodeType,
      position,
      data: {
        label: n.id,
        stepType: n.type,
        fidelity: n.fidelity,
        config: n.config,
      },
      className: `oiw-node oiw-node--${n.type.replace(/\./g, '-')}`,
    });
  }

  return result;
}

export function toReactFlowEdges(flow: IntegrationFlow): Edge[] {
  return flow.spec.edges.map((e: FlowEdge, i: number) => ({
    id: `edge-${i}-${e.from}-${e.to}`,
    source: e.from,
    target: e.to,
    label: e.condition,
    animated: e.condition === 'default',
    type: e.condition ? 'smoothstep' : 'default',
  }));
}

export function fidelityColor(fidelity: string): string {
  switch (fidelity) {
    case 'compatible-subset':
      return '#10b981';
    case 'simulated':
      return '#f59e0b';
    case 'authoring-only':
      return '#6b7280';
    case 'tenant-required':
      return '#ef4444';
    case 'unsupported':
      return '#ef4444';
    default:
      return '#8b91a7';
  }
}
