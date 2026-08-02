/**
 * PatchPreviewDialog — shows a semantic diff of the changes the agent
 * just applied, with color-coded added/removed/changed items.
 *
 * WP-04 Task 9 / spec §12.6 (semantic diff): every change is shown as
 * a diff. Added nodes are green, removed nodes are red, changed config
 * is yellow.
 *
 * Props:
 *  - implementResult: the AgentImplementResponse from POST /agents:implement
 *  - onClose: called when the user closes the dialog
 *
 * The dialog derives a structural diff from the implement response's
 * step results (which flow.patch operations were applied). It does NOT
 * re-fetch the flow from the server — that's the caller's job if a
 * full semantic diff is needed.
 */

import type { AgentImplementResponse, StepResult } from '../../api';

interface PatchPreviewDialogProps {
  implementResult: AgentImplementResponse;
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
      // The implement response doesn't echo back the operations; we
      // rely on the step's description to give us a hint.
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

export function PatchPreviewDialog({ implementResult, onClose }: PatchPreviewDialogProps) {
  const entries = deriveDiffEntries(implementResult.stepResults);
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

          {/* Diff entries */}
          <section className="patch-section">
            <h3 className="patch-section__title">Changes ({entries.length})</h3>
            {entries.length === 0 ? (
              <p className="muted">No structural changes were applied.</p>
            ) : (
              <ul className="diff-list">
                {entries.map((e, i) => (
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
