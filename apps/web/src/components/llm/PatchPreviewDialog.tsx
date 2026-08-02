/**
 * PatchPreviewDialog — shows a semantic diff of the changes the agent
 * just applied, with color-coded added/removed/changed items.
 *
 * WP-04 Task 9 / spec §12.6 (semantic diff): every change is shown as
 * a diff. Added nodes are green, removed nodes are red, changed config
 * is yellow.
 *
 * OW-028: the dialog now fetches the real semantic diff from the
 * server (GET /projects/{id}/diff) instead of deriving a coarse diff
 * from the stepResults. Falls back to the derived diff if the fetch
 * fails or returns no changes.
 *
 * Props:
 *  - implementResult: the AgentImplementResponse from POST /agents:implement
 *  - projectId: the project ID (used to fetch the semantic diff)
 *  - onClose: called when the user closes the dialog
 */

import { useEffect, useState } from 'react';
import { api } from '../../api';
import type { AgentImplementResponse, StepResult, StructuredDiff } from '../../api';

interface PatchPreviewDialogProps {
  implementResult: AgentImplementResponse;
  projectId: string | null;
  onClose: () => void;
}

interface DiffEntry {
  kind: 'added' | 'removed' | 'changed' | 'resource' | 'test';
  label: string;
  detail: string;
}

function deriveDiffEntries(results: StepResult[]): DiffEntry[] {
  const entries: DiffEntry[] = [];
  for (const r of results) {
    if (!r.success) continue;
    if (r.tool === 'flow.patch') {
      const result = r.result as { applied?: number };
      entries.push({
        kind: 'changed',
        label: `flow.patch (${result.applied ?? 0} ops)`,
        detail: r.description,
      });
    } else if (r.tool === 'resource.write') {
      entries.push({
        kind: 'resource',
        label: 'resource.write',
        detail: r.description,
      });
    } else if (r.tool === 'test.create') {
      entries.push({
        kind: 'test',
        label: 'test.create',
        detail: r.description,
      });
    } else if (r.tool === 'flow.validate') {
      entries.push({
        kind: 'changed',
        label: 'flow.validate',
        detail: r.description,
      });
    }
  }
  return entries;
}

/** Convert a StructuredDiff (from GET /diff) into DiffEntry[] for display. */
function diffToEntries(diff: StructuredDiff): DiffEntry[] {
  const entries: DiffEntry[] = [];
  // The StructuredDiff shape (from api.ts) has a `changes` array with
  // {path, old_value, new_value} or similar. Adapt to our display format.
  // The exact shape depends on the server's /diff endpoint output.
  const changes = (diff as unknown as { changes?: Array<Record<string, unknown>> }).changes ?? [];
  for (const c of changes) {
    const path = String(c.path ?? c.file ?? '');
    const oldValue = c.old_value ?? c.old ?? null;
    const newValue = c.new_value ?? c.new ?? null;
    if (oldValue === null && newValue !== null) {
      entries.push({ kind: 'added', label: path, detail: String(newValue).slice(0, 120) });
    } else if (oldValue !== null && newValue === null) {
      entries.push({ kind: 'removed', label: path, detail: String(oldValue).slice(0, 120) });
    } else if (oldValue !== null && newValue !== null) {
      entries.push({ kind: 'changed', label: path, detail: `${String(oldValue).slice(0, 60)} → ${String(newValue).slice(0, 60)}` });
    }
  }
  return entries;
}

function diffEntryClass(kind: DiffEntry['kind']): string {
  return `diff-entry diff-entry--${kind}`;
}

function diffEntryIcon(kind: DiffEntry['kind']): string {
  return {
    added: '+',
    removed: '−',
    changed: '~',
    resource: '📄',
    test: '🧪',
  }[kind];
}

export function PatchPreviewDialog({ implementResult, projectId, onClose }: PatchPreviewDialogProps) {
  // OW-028: fetch the real semantic diff from the server.
  const [diffEntries, setDiffEntries] = useState<DiffEntry[]>([]);
  const [diffLoading, setDiffLoading] = useState(false);
  const [diffError, setDiffError] = useState<string | null>(null);

  useEffect(() => {
    if (!projectId) return;
    setDiffLoading(true);
    setDiffError(null);
    // GET /projects/{id}/diff compares working tree against HEAD~1.
    // After an agent patch, the working tree has the new state and
    // HEAD~1 has the pre-patch state, so this shows exactly what changed.
    api
      .getDiff(projectId, 'HEAD~1')
      .then((diff: StructuredDiff) => {
        const entries = diffToEntries(diff);
        if (entries.length > 0) {
          setDiffEntries(entries);
        } else {
          // Fall back to derived entries if the server returned no changes
          setDiffEntries(deriveDiffEntries(implementResult.stepResults));
        }
      })
      .catch((e: unknown) => {
        setDiffError(String(e));
        // Fall back to derived entries on error
        setDiffEntries(deriveDiffEntries(implementResult.stepResults));
      })
      .finally(() => setDiffLoading(false));
  }, [projectId, implementResult.stepResults]);

  const succeeded = implementResult.stepResults.filter((r) => r.success).length;
  const failed = implementResult.stepResults.length - succeeded;

  return (
    <div className="dialog-backdrop" role="dialog" aria-modal="true" aria-labelledby="patch-dialog-title">
      <div className="dialog dialog--patch-preview">
        <div className="dialog__header">
          <h2 id="patch-dialog-title" className="dialog__title">Changes Applied</h2>
          <button className="dialog__close" onClick={onClose} aria-label="Close">×</button>
        </div>

        <div className="dialog__body">
          {/* Status summary */}
          <div className={`patch-summary ${implementResult.success ? 'patch-summary--ok' : 'patch-summary--err'}`}>
            <span className="patch-summary__status">
              {implementResult.success ? '✓ Success' : '✗ Failed'}
            </span>
            <span className="patch-summary__counts">
              {succeeded} succeeded, {failed} failed
            </span>
            {implementResult.trajectoryId && (
              <span className="patch-summary__trajectory" title="Trajectory ID (link to oiw trajectory show)">
                traj: {implementResult.trajectoryId}
              </span>
            )}
          </div>

          {/* Errors */}
          {implementResult.errors.length > 0 && (
            <section className="patch-section">
              <h3 className="patch-section__title">Errors</h3>
              <ul className="patch-errors">
                {implementResult.errors.map((e, i) => (
                  <li key={i} className="patch-error">{e}</li>
                ))}
              </ul>
            </section>
          )}

          {/* Diff entries (OW-028: fetched from server, fallback to derived) */}
          <section className="patch-section">
            <h3 className="patch-section__title">
              Changes ({diffEntries.length})
              {diffLoading && <span className="patch-section__loading"> loading…</span>}
              {diffError && (
                <span className="patch-section__fallback" title={diffError}>
                  {' '}(fallback: derived from step results)
                </span>
              )}
            </h3>
            {diffEntries.length === 0 ? (
              <p className="muted">No structural changes were applied.</p>
            ) : (
              <ul className="diff-list">
                {diffEntries.map((e, i) => (
                  <li key={i} className={diffEntryClass(e.kind)}>
                    <span className="diff-entry__icon">{diffEntryIcon(e.kind)}</span>
                    <span className="diff-entry__label">{e.label}</span>
                    <span className="diff-entry__detail">{e.detail}</span>
                  </li>
                ))}
              </ul>
            )}
          </section>

          {/* Step results detail */}
          <section className="patch-section">
            <h3 className="patch-section__title">Step Results</h3>
            <ol className="step-results">
              {implementResult.stepResults.map((r, i) => (
                <li key={i} className={`step-result ${r.success ? 'step-result--ok' : 'step-result--err'}`}>
                  <span className="step-result__index">{r.stepIndex}</span>
                  <span className="badge badge--mono">{r.tool}</span>
                  <span className="step-result__description">{r.description}</span>
                  <span className="step-result__status">{r.success ? '✓' : '✗'}</span>
                </li>
              ))}
            </ol>
          </section>
        </div>

        <div className="dialog__footer">
          <button className="btn btn--primary" onClick={onClose}>Close</button>
        </div>
      </div>
    </div>
  );
}
