/**
 * OIW API client.
 * Generated types derived from packages/api-spec/openapi.yaml (OW-015 / WP-09 A-002)
 * backed by the typed client in ./api/client.ts.
 */

import {
  fetchJSON,
  defaultApiClient,
  type SchemaExperimentSummary,
  type SchemaExperimentRecord,
  type SchemaRung,
  type SchemaLawRecord,
  type SchemaCalibrationSummary,
  type SchemaCalibrationReport,
} from './api/client';
export * from './api/client';

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
  body_preview: string | null;
  headers: Record<string, unknown> | null;
  properties: Record<string, unknown> | null;
  duration_ms: number | null;
  exception_type: string | null;
}

export interface OutboundCall {
  target: string;
  method: string;
  url: string;
  body?: string;
  requestHeaders?: Record<string, unknown>;
}

export interface SimulationResult {
  status: 'COMPLETED' | 'FAILED' | 'RUNNING';
  duration_ms: number;
  trace: TraceEntry[];
  outbound_calls: OutboundCall[];
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
  health: () => defaultApiClient.health(),
  listProjects: () => defaultApiClient.listProjects() as unknown as Promise<ProjectSummary[]>,
  getProject: (id: string) => defaultApiClient.getProject(id) as unknown as Promise<unknown>,
  listFlows: (projectId: string) => defaultApiClient.listFlows(projectId) as unknown as Promise<FlowSummary[]>,
  getFlow: (projectId: string, flowId: string) =>
    defaultApiClient.getFlow(projectId, flowId) as unknown as Promise<IntegrationFlow>,
  patchFlow: (projectId: string, flowId: string, operations: unknown[], baseRevision?: string) =>
    defaultApiClient.patchFlow(projectId, flowId, operations, baseRevision),
  validate: (projectId: string, strict = false) =>
    defaultApiClient.validate(projectId, strict) as unknown as Promise<ValidationResult>,
  runTests: (projectId: string, flowId?: string) =>
    defaultApiClient.runTests(projectId, flowId) as unknown as Promise<TestResult[]>,
  build: (projectId: string, targetProfile: string) =>
    defaultApiClient.build(projectId, targetProfile) as unknown as Promise<BuildResult>,
  gitStatus: (projectId: string) =>
    defaultApiClient.gitStatus(projectId) as unknown as Promise<GitStatus>,
  simulate: (
    projectId: string,
    flowId: string,
    req: {
      body_inline?: string;
      body_file?: string;
      headers?: Record<string, string>;
      mocks?: Array<{ target: string; respond: { status: number; body?: string } }>;
    }
  ) => defaultApiClient.simulate(projectId, flowId, req) as unknown as Promise<SimulationResult>,
  listResources: (projectId: string) =>
    defaultApiClient.listResources(projectId) as unknown as Promise<ResourceSummary[]>,
  getResource: (projectId: string, resourcePath: string) =>
    defaultApiClient.getResource(projectId, resourcePath) as unknown as Promise<ResourceContent>,
  writeResource: (projectId: string, resourcePath: string, content: string) =>
    defaultApiClient.writeResource(projectId, resourcePath, content) as unknown as Promise<ResourceContent>,
  getDiff: (projectId: string, rev = 'HEAD~1') =>
    defaultApiClient.getDiff(projectId, rev) as unknown as Promise<StructuredDiff>,

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

  // ---------------------------------------------------------------
  // EMG endpoints (WP-06 E-003 + WP-08 PR-3/PR-10).
  // ---------------------------------------------------------------
  emgStats: () => fetchJSON<EmgStats>('/emg/stats'),
  emgInsights: (projectId: string) =>
    fetchJSON<EmgInsightSummary[]>(`/projects/${projectId}/emg/insights`),
  emgInsightDetail: (insightId: string) =>
    fetchJSON<EmgInsightDetail>(`/emg/insights/${encodeURIComponent(insightId)}`),

  // ---------------------------------------------------------------
  // Experiments & Laws (WP-10 Track D / H1).
  // ---------------------------------------------------------------
  listExperiments: () => defaultApiClient.listExperiments(),
  getExperiment: (id: string) => defaultApiClient.getExperiment(id),
  listLaws: (params?: { status?: 'candidate' | 'ratified' | 'retired'; scope?: string }) =>
    defaultApiClient.listLaws(params),

  // ---------------------------------------------------------------
  // Calibrations (WP-10 B-003 / H2).
  // ---------------------------------------------------------------
  listCalibrations: (projectId: string) => defaultApiClient.listCalibrations(projectId),
  getCalibration: (projectId: string, artifactId: string) =>
    defaultApiClient.getCalibration(projectId, artifactId),
};

export type ExperimentSummary = SchemaExperimentSummary;
export type ExperimentRecord = SchemaExperimentRecord;
export type RungRecord = SchemaRung;
export type LawRecord = SchemaLawRecord;
export type CalibrationSummary = SchemaCalibrationSummary;
export type CalibrationReport = SchemaCalibrationReport;

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
  emg?: EmgHit | null;
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
  emg?: EmgHit | null;
}

// -----------------------------------------------------------------
// EMG types (WP-08 PR-10 / OW-032). The UI must render what the
// server actually reports — never a hardcoded guess.
// -----------------------------------------------------------------

/** Truthful EMG retrieval metadata attached to agent plan/implement responses. */
export interface EmgHit {
  used: boolean;
  confidence: number;
  insightId?: string | null;
  taskId?: string | null;
  reason: string;
  provenance?: {
    expertTrajectoryId?: string | null;
    matchStage?: string | null;
  } | null;
}

export interface EmgInsightSummary {
  id: string;
  taskId: string;
  confidence: number;
  supportCount: number;
  workflowStepCount: number;
  correctionCount: number;
  provenance: Record<string, unknown> | null;
  approval: string;
}

export interface EmgInsightDetail extends EmgInsightSummary {
  successfulWorkflow: Array<Record<string, unknown>>;
  corrections: Array<Record<string, unknown>>;
}

export interface EmgStats {
  totalTrajectories: number;
  approvedInsights: number;
  crossTaskEdges: number;
  retrievalHitRate: number;
  adapterFamilies: string[];
  embeddingBackend: string;
  embeddingModel: string;
  embeddingDim: number;
  storePath: string;
  compatible: boolean;
}
