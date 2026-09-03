import { useState, useEffect, useCallback } from 'react';
import { api } from '../api';
import type { ProjectSummary, FlowSummary, ResourceSummary } from '../api';

export function useProjectWorkspace() {
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [selectedProject, setSelectedProject] = useState<string | null>(null);
  const [flows, setFlows] = useState<FlowSummary[]>([]);
  const [selectedFlow, setSelectedFlow] = useState<string | null>(null);
  const [resources, setResources] = useState<ResourceSummary[]>([]);
  const [selectedResource, setSelectedResource] = useState<ResourceSummary | null>(null);
  const [viewMode, setViewMode] = useState<'canvas' | 'resource'>('canvas');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchProjects = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.listProjects();
      setProjects(data);
      setError(null);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchProjects();
  }, [fetchProjects]);

  useEffect(() => {
    if (!selectedProject) {
      setFlows([]);
      setSelectedFlow(null);
      setResources([]);
      setSelectedResource(null);
      setViewMode('canvas');
      return;
    }
    setFlows([]);
    setSelectedFlow(null);
    setResources([]);
    setSelectedResource(null);
    setViewMode('canvas');

    let isMounted = true;
    Promise.all([
      api.listFlows(selectedProject),
      api.listResources(selectedProject),
    ])
      .then(([flowList, resList]) => {
        if (!isMounted) return;
        setFlows(flowList);
        setResources(resList);
        setError(null);
      })
      .catch((e) => {
        if (!isMounted) return;
        setError(String(e));
      });

    return () => {
      isMounted = false;
    };
  }, [selectedProject]);

  return {
    projects,
    selectedProject,
    setSelectedProject,
    flows,
    selectedFlow,
    setSelectedFlow,
    resources,
    selectedResource,
    setSelectedResource,
    viewMode,
    setViewMode,
    loading,
    error,
    setError,
    fetchProjects,
  };
}
