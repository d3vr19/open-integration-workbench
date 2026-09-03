import { useState, useEffect, useCallback, useRef } from 'react';
import type { Connection, Edge, Node, NodeMouseHandler, OnNodesDelete, OnEdgesDelete } from 'reactflow';
import { api } from '../api';
import type { IntegrationFlow } from '../api';
import { toReactFlowNodes, toReactFlowEdges } from '../flow-utils';

let nodeIdCounter = 0;
function genNodeId(type: string): string {
  nodeIdCounter += 1;
  const prefix = type.split('.').pop() || 'node';
  return `${prefix}-${Date.now().toString(36).slice(-4)}-${nodeIdCounter}`;
}

export function useFlowEditor(selectedProject: string | null, selectedFlow: string | null) {
  const [flow, setFlow] = useState<IntegrationFlow | null>(null);
  const [rfNodes, setRfNodes] = useState<Node[]>([]);
  const [rfEdges, setRfEdges] = useState<Edge[]>([]);
  const [selectedNode, setSelectedNode] = useState<Node | null>(null);
  const [pendingOps, setPendingOps] = useState<unknown[]>([]);
  const [dirty, setDirty] = useState(false);
  const [flowLoading, setFlowLoading] = useState(false);
  const [flowError, setFlowError] = useState<string | null>(null);
  const dragType = useRef<string | null>(null);

  useEffect(() => {
    if (!selectedProject || !selectedFlow) {
      setFlow(null);
      setRfNodes([]);
      setRfEdges([]);
      setPendingOps([]);
      setDirty(false);
      setSelectedNode(null);
      return;
    }

    setFlow(null);
    setPendingOps([]);
    setDirty(false);
    setSelectedNode(null);
    setFlowLoading(true);

    let isMounted = true;
    api
      .getFlow(selectedProject, selectedFlow)
      .then((f) => {
        if (!isMounted) return;
        setFlow(f);
        setRfNodes(toReactFlowNodes(f));
        setRfEdges(toReactFlowEdges(f));
        setFlowError(null);
      })
      .catch((e) => {
        if (!isMounted) return;
        setFlowError(String(e));
      })
      .finally(() => {
        if (isMounted) setFlowLoading(false);
      });

    return () => {
      isMounted = false;
    };
  }, [selectedProject, selectedFlow]);

  const refreshFlow = useCallback(async () => {
    if (!selectedProject || !selectedFlow) return;
    try {
      const f = await api.getFlow(selectedProject, selectedFlow);
      setFlow(f);
      setRfNodes(toReactFlowNodes(f));
      setRfEdges(toReactFlowEdges(f));
      setPendingOps([]);
      setDirty(false);
      setFlowError(null);
    } catch (e) {
      setFlowError(String(e));
    }
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

  const onDrop = useCallback(
    (e: React.DragEvent) => {
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
      setPendingOps((ops) => [
        ...ops,
        { op: 'addNode', node: { id: nodeId, type: stepType, config: {}, fidelity: 'simulated' } },
      ]);
      setDirty(true);
      dragType.current = null;
    },
    [flow],
  );

  const updateNodeId = useCallback((oldId: string, newId: string) => {
    setRfNodes((nds) => nds.map((n) => (n.id === oldId ? { ...n, id: newId } : n)));
    setRfEdges((eds) =>
      eds.map((e) => ({
        ...e,
        source: e.source === oldId ? newId : e.source,
        target: e.target === oldId ? newId : e.target,
      })),
    );
    setSelectedNode((sn) => (sn && sn.id === oldId ? { ...sn, id: newId } : sn));
    setDirty(true);
  }, []);

  const updateNodeConfig = useCallback((nodeId: string, key: string, value: string) => {
    setRfNodes((nds) =>
      nds.map((n) => {
        if (n.id !== nodeId) return n;
        const data = n.data as { config?: Record<string, unknown> };
        return { ...n, data: { ...data, config: { ...data.config, [key]: value } } };
      }),
    );
    setDirty(true);
  }, []);

  const save = useCallback(async () => {
    if (!selectedProject || !selectedFlow || pendingOps.length === 0) return;
    setFlowLoading(true);
    setFlowError(null);
    try {
      const headResp = await fetch(`/api/v1/projects/${selectedProject}/git/status`).then((r) => r.json());
      const baseRevision = headResp.head_sha || 'unknown';
      await api.patchFlow(selectedProject, selectedFlow, pendingOps as unknown[], baseRevision);
      setPendingOps([]);
      setDirty(false);
      await refreshFlow();
    } catch (e) {
      setFlowError(String(e));
    } finally {
      setFlowLoading(false);
    }
  }, [selectedProject, selectedFlow, pendingOps, refreshFlow]);

  return {
    flow,
    rfNodes,
    rfEdges,
    selectedNode,
    pendingOps,
    dirty,
    flowLoading,
    flowError,
    setFlowError,
    refreshFlow,
    onNodeClick,
    onNodeDragStop,
    onConnect,
    onNodesDelete,
    onEdgesDelete,
    onDragStart,
    onDragOver,
    onDrop,
    updateNodeId,
    updateNodeConfig,
    save,
  };
}
