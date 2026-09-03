import { useState, useCallback } from 'react';
import { api } from '../api';
import type { ValidationResult, TestResult, BuildResult, GitStatus, SimulationResult, StructuredDiff } from '../api';

export function useProjectActions(selectedProject: string | null, selectedFlow: string | null) {
  const [validation, setValidation] = useState<ValidationResult | null>(null);
  const [tests, setTests] = useState<TestResult[] | null>(null);
  const [build, setBuild] = useState<BuildResult | null>(null);
  const [gitStatus, setGitStatus] = useState<GitStatus | null>(null);
  const [diff, setDiff] = useState<StructuredDiff | null>(null);
  const [simulation, setSimulation] = useState<SimulationResult | null>(null);
  const [showRawTrace, setShowRawTrace] = useState(false);
  const [simulating, setSimulating] = useState(false);
  const [actionLoading, setActionLoading] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const runValidate = useCallback(async () => {
    if (!selectedProject) return;
    setActionLoading(true);
    setActionError(null);
    try {
      const result = await api.validate(selectedProject);
      setValidation(result);
    } catch (e) {
      setActionError(String(e));
    } finally {
      setActionLoading(false);
    }
  }, [selectedProject]);

  const runTests = useCallback(async () => {
    if (!selectedProject) return;
    setActionLoading(true);
    setActionError(null);
    try {
      const result = await api.runTests(selectedProject, selectedFlow ?? undefined);
      setTests(result);
    } catch (e) {
      setActionError(String(e));
    } finally {
      setActionLoading(false);
    }
  }, [selectedProject, selectedFlow]);

  const runBuild = useCallback(async () => {
    if (!selectedProject) return;
    setActionLoading(true);
    setActionError(null);
    try {
      const result = await api.build(selectedProject, 'sap-cloud-integration-2026-07');
      setBuild(result);
    } catch (e) {
      setActionError(String(e));
    } finally {
      setActionLoading(false);
    }
  }, [selectedProject]);

  const runSimulation = useCallback(async () => {
    if (!selectedProject || !selectedFlow) return;
    setSimulating(true);
    setActionError(null);
    try {
      const result = await api.simulate(selectedProject, selectedFlow, { body_inline: '{}' });
      setSimulation(result);
    } catch (e) {
      setActionError(String(e));
    } finally {
      setSimulating(false);
    }
  }, [selectedProject, selectedFlow]);

  const viewDiff = useCallback(async () => {
    if (!selectedProject) return;
    setActionLoading(true);
    setActionError(null);
    try {
      const result = await api.getDiff(selectedProject);
      setDiff(result);
    } catch (e) {
      setActionError(String(e));
    } finally {
      setActionLoading(false);
    }
  }, [selectedProject]);

  const loadGitStatus = useCallback(async () => {
    if (!selectedProject) return;
    setActionLoading(true);
    setActionError(null);
    try {
      const result = await api.gitStatus(selectedProject);
      setGitStatus(result);
    } catch (e) {
      setActionError(String(e));
    } finally {
      setActionLoading(false);
    }
  }, [selectedProject]);

  return {
    validation,
    tests,
    build,
    gitStatus,
    diff,
    simulation,
    showRawTrace,
    setShowRawTrace,
    simulating,
    actionLoading,
    actionError,
    setActionError,
    runValidate,
    runTests,
    runBuild,
    runSimulation,
    viewDiff,
    loadGitStatus,
  };
}
