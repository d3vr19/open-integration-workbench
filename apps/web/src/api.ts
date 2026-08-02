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

export interface TraceEntry {
  node_id: string;
  timestamp: number;
  direction: 'enter' | 'exit' | 'error' | 'complete';
  summary: string;
}

export interface SimulationResult {
  status: 'COMPLETED' | 'FAILED' | 'RUNNING';
  duration_ms: number;
  trace: TraceEntry[];
  outbound_calls: Array<{ target: string; method: string; url: string }>;
  headers: Record<string, unknown>;
  properties: Record<string, unknown>;
}

export interface ResourceSummary {
  path: string;
  name: string;
  resource_type: string;
  language: string;
  size: number;
}

export interface ResourceContent {
  path: string;
  content: string;
  language: string;
  resource_type: string;
  size: number;
}

export interface StructuredDiff {
  base_sha: string;
  head_sha: string;
  total_changes: number;
  flows: { added: string[]; modified: string[]; removed: string[] };
  resources: { added: string[]; modified: string[]; removed: string[] };
  tests: { added: string[]; modified: string[]; removed: string[] };
  other: Array<{ path: string; status: string; category: string }>;
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
  patchFlow: (projectId: string, flowId: string, operations: unknown[], baseRevision?: string) =>
    fetchJSON<{ applied: number; new_revision: string | null; flow_id: string }>(
      `/projects/${projectId}/flows/${flowId}`,
      {
        method: 'PATCH',
        body: JSON.stringify({ operations, base_revision: baseRevision }),
      },
    ),
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
  simulate: (projectId: string, flowId: string, req: {
    body_inline?: string;
    body_file?: string;
    headers?: Record<string, string>;
    mocks?: Array<{ target: string; respond: { status: number; body?: string } }>;
  }) =>
    fetchJSON<SimulationResult>(`/projects/${projectId}/flows/${flowId}/simulate`, {
      method: 'POST',
      body: JSON.stringify(req),
    }),
  listResources: (projectId: string) =>
    fetchJSON<ResourceSummary[]>(`/projects/${projectId}/resources`),
  getResource: (projectId: string, resourcePath: string) =>
    fetchJSON<ResourceContent>(`/projects/${projectId}/resources/${resourcePath}`),
  writeResource: (projectId: string, resourcePath: string, content: string) =>
    fetchJSON<ResourceContent>(`/projects/${projectId}/resources/${resourcePath}`, {
      method: 'PUT',
      body: JSON.stringify({ content }),
    }),
  getDiff: (projectId: string, rev = 'HEAD~1') =>
    fetchJSON<StructuredDiff>(`/projects/${projectId}/diff?rev=${encodeURIComponent(rev)}`),

  // -----------------------------------------------------------------
  // Agent endpoints (WP-04 Task 7 + Task 9).
  // Spec ref: §21.1 (POST /projects/{id}/agents:plan,
  //                     POST /projects/{id}/agents:implement).
  // -----------------------------------------------------------------
  plan: (projectId: string, requirement: string, flowId?: string) =>
    fetchJSON<AgentPlanResponse>(`/projects/${projectId}/agents:plan`, {
      method: 'POST',
      body: JSON.stringify({ requirement, flowId }),
    }),
  implement: (projectId: string, requirement: string, flowId?: string, dryRun = false) =>
    fetchJSON<AgentImplementResponse>(`/projects/${projectId}/agents:implement`, {
      method: 'POST',
      body: JSON.stringify({ requirement, flowId, dryRun }),
    }),
};

// -----------------------------------------------------------------
// Agent + trajectory types (WP-04 Task 9).
// -----------------------------------------------------------------

export interface NormalizedRequirement {
  intent: string;                 // create-flow | modify-flow | fix-flow | add-test | refactor | general
  sourceProtocol?: string | null;
  targetProtocol?: string | null;
  operations: string[];
  archetype?: string | null;
  raw: string;
}

export interface PlanStep {
  index: number;
  tool: string;                   // flow.patch | resource.write | test.create | flow.validate | test.run
  description: string;
  arguments: Record<string, unknown>;
}

export interface AgentPlanResponse {
  requirement: NormalizedRequirement;
  steps: PlanStep[];
  assumptions: string[];
  risks: string[];
}

export interface StepResult {
  stepIndex: number;
  tool: string;
  description: string;
  result: Record<string, unknown>;
  success: boolean;
  error?: string;
}

export interface AgentImplementResponse {
  plan: {
    requirement: NormalizedRequirement;
    steps: PlanStep[];
    assumptions: string[];
    risks: string[];
  };
  stepResults: StepResult[];
  success: boolean;
  errors: string[];
  trajectoryId?: string | null;
}
