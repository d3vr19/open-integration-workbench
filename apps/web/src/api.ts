/**
 * OIW API client — thin wrapper around fetch.
 * Spec ref: §21.1 (REST Endpoints).
 *
 * In production this will be generated from packages/api-spec/openapi.yaml
 * (tracked as OW-015). For now, hand-written.
 */

const API_BASE = '/api/v1';

async function fetchJSON<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...options?.headers,
    },
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail));
  }
  return res.json();
}

export interface ProjectSummary {
  id: string;
  name: string;
  path: string;
  created: string;
  flow_count: number;
  test_count: number;
}

export interface FlowSummary {
  id: string;
  name: string;
  version: number;
  node_count: number;
  test_count: number;
  labels: Record<string, string>;
}

export interface FlowNode {
  id: string;
  type: string;
  config: Record<string, unknown>;
  fidelity: string;
}

export interface FlowEdge {
  from: string;
  to: string;
  condition?: string;
}

export interface IntegrationFlow {
  apiVersion: string;
  kind: string;
  metadata: {
    id: string;
    name: string;
    version: number;
    labels: Record<string, string>;
  };
  spec: {
    entrypoints: FlowNode[];
    nodes: FlowNode[];
    edges: FlowEdge[];
    extensions: Record<string, unknown>;
    errorHandling?: {
      defaultExceptionSubprocess: {
        steps: FlowNode[];
      };
    };
  };
  diagram: {
    nodes: Array<{ id: string; position: { x: number; y: number }; lane?: string }>;
    edges: Array<{ from: string; to: string; condition?: string }>;
  } | null;
}

export interface ValidationResult {
  errors: string[];
  warnings: string[];
  error_count: number;
  warning_count: number;
  passed: boolean;
}

export interface TestResult {
  flow_id: string;
  test_name: string;
  passed: boolean;
  duration_ms: number;
  failures: string[];
}

export interface BuildResult {
  out_dir: string;
  manifest_path: string;
  digest: string;
  compiler_version: string;
  target_profile: string;
  entry_count: number;
}

export interface GitStatus {
  branch: string;
  head_sha: string;
  dirty: boolean;
  ahead: number;
  last_build_digest: string | null;
  last_build_target: string | null;
}

export const api = {
  health: () => fetchJSON<{ status: string; version: string }>('/health'),
  listProjects: () => fetchJSON<ProjectSummary[]>('/projects'),
  getProject: (id: string) =>
    fetchJSON<unknown>(`/projects/${id}`),
  listFlows: (projectId: string) =>
    fetchJSON<FlowSummary[]>(`/projects/${projectId}/flows`),
  getFlow: (projectId: string, flowId: string) =>
    fetchJSON<IntegrationFlow>(`/projects/${projectId}/flows/${flowId}`),
  validate: (projectId: string, strict = false) =>
    fetchJSON<ValidationResult>(`/projects/${projectId}/validate`, {
      method: 'POST',
      body: JSON.stringify({ strict }),
    }),
  runTests: (projectId: string, flowId?: string) =>
    fetchJSON<TestResult[]>(`/projects/${projectId}/tests:run`, {
      method: 'POST',
      body: JSON.stringify({ flow_id: flowId }),
    }),
  build: (projectId: string, targetProfile: string) =>
    fetchJSON<BuildResult>(`/projects/${projectId}/builds`, {
      method: 'POST',
      body: JSON.stringify({ target_profile: targetProfile }),
    }),
  gitStatus: (projectId: string) =>
    fetchJSON<GitStatus>(`/projects/${projectId}/git/status`),
};
