/**
 * OIW API Client — typed wrapper using OpenAPI schemas.
 * Generated from packages/api-spec/openapi.yaml via openapi-typescript (OW-015 / WP-09 A-002).
 */

import type { paths, components } from './gen/schema';

export type { paths, components };

const API_BASE = '/api/v1';

export async function fetchJSON<T>(path: string, options?: RequestInit, base = API_BASE): Promise<T> {
  const res = await fetch(`${base}${path}`, {
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

export type SchemaProjectSummary = components['schemas']['ProjectSummary'];
export type SchemaProject = components['schemas']['Project'];
export type SchemaFlowSummary = components['schemas']['FlowSummary'];
export type SchemaIntegrationFlow = components['schemas']['IntegrationFlow'];
export type SchemaValidationResult = components['schemas']['ValidationResult'];
export type SchemaTestResult = components['schemas']['TestResult'];
export type SchemaBuildResult = components['schemas']['BuildResult'];
export type SchemaGitStatus = components['schemas']['GitStatus'];
export type SchemaTraceEntry = components['schemas']['TraceEntry'];
export type SchemaSimulationResult = components['schemas']['SimulationResult'];
export type SchemaResourceSummary = components['schemas']['ResourceSummary'];
export type SchemaResourceContent = components['schemas']['ResourceContent'];
export type SchemaStructuredDiff = components['schemas']['StructuredDiff'];
export type SchemaPatchResponse = components['schemas']['PatchResponse'];
export type SchemaPatchRequest = components['schemas']['PatchRequest'];
export type SchemaSimulateRequest = components['schemas']['SimulateRequest'];

export class ApiClient {
  readonly base: string;

  constructor(base = API_BASE) {
    this.base = base;
  }

  private fetch<T>(path: string, options?: RequestInit): Promise<T> {
    return fetchJSON<T>(path, options, this.base);
  }

  health() {
    return this.fetch<{ status: string; version: string }>('/health');
  }

  listProjects(workspace?: string) {
    const q = workspace ? `?workspace=${encodeURIComponent(workspace)}` : '';
    return this.fetch<SchemaProjectSummary[]>(`/projects${q}`);
  }

  getProject(id: string) {
    return this.fetch<SchemaProject>(`/projects/${encodeURIComponent(id)}`);
  }

  listFlows(projectId: string) {
    return this.fetch<SchemaFlowSummary[]>(`/projects/${encodeURIComponent(projectId)}/flows`);
  }

  getFlow(projectId: string, flowId: string) {
    return this.fetch<SchemaIntegrationFlow>(
      `/projects/${encodeURIComponent(projectId)}/flows/${encodeURIComponent(flowId)}`
    );
  }

  patchFlow(projectId: string, flowId: string, operations: unknown[], baseRevision?: string) {
    return this.fetch<{ applied: number; new_revision: string | null; flow_id: string }>(
      `/projects/${encodeURIComponent(projectId)}/flows/${encodeURIComponent(flowId)}`,
      {
        method: 'PATCH',
        body: JSON.stringify({ operations, base_revision: baseRevision }),
      }
    );
  }

  validate(projectId: string, strict = false) {
    return this.fetch<SchemaValidationResult>(
      `/projects/${encodeURIComponent(projectId)}/validate`,
      {
        method: 'POST',
        body: JSON.stringify({ strict }),
      }
    );
  }

  runTests(projectId: string, flowId?: string) {
    return this.fetch<SchemaTestResult[]>(
      `/projects/${encodeURIComponent(projectId)}/tests:run`,
      {
        method: 'POST',
        body: JSON.stringify({ flow_id: flowId }),
      }
    );
  }

  build(projectId: string, targetProfile: string) {
    return this.fetch<SchemaBuildResult>(
      `/projects/${encodeURIComponent(projectId)}/builds`,
      {
        method: 'POST',
        body: JSON.stringify({ target_profile: targetProfile }),
      }
    );
  }

  gitStatus(projectId: string) {
    return this.fetch<SchemaGitStatus>(
      `/projects/${encodeURIComponent(projectId)}/git/status`
    );
  }

  simulate(
    projectId: string,
    flowId: string,
    req: {
      body_inline?: string;
      body_file?: string;
      headers?: Record<string, string>;
      mocks?: Array<{ target: string; respond: { status: number; body?: string } }>;
    }
  ) {
    return this.fetch<SchemaSimulationResult>(
      `/projects/${encodeURIComponent(projectId)}/flows/${encodeURIComponent(flowId)}/simulate`,
      {
        method: 'POST',
        body: JSON.stringify(req),
      }
    );
  }

  listResources(projectId: string) {
    return this.fetch<SchemaResourceSummary[]>(
      `/projects/${encodeURIComponent(projectId)}/resources`
    );
  }

  getResource(projectId: string, resourcePath: string) {
    return this.fetch<SchemaResourceContent>(
      `/projects/${encodeURIComponent(projectId)}/resources/${resourcePath}`
    );
  }

  writeResource(projectId: string, resourcePath: string, content: string) {
    return this.fetch<SchemaResourceContent>(
      `/projects/${encodeURIComponent(projectId)}/resources/${resourcePath}`,
      {
        method: 'PUT',
        body: JSON.stringify({ content }),
      }
    );
  }

  getDiff(projectId: string, rev = 'HEAD~1') {
    return this.fetch<SchemaStructuredDiff>(
      `/projects/${encodeURIComponent(projectId)}/diff?rev=${encodeURIComponent(rev)}`
    );
  }
}

export const defaultApiClient = new ApiClient();
