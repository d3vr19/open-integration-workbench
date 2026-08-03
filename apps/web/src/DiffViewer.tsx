/**
 * Semantic diff viewer.
 * Spec ref: §10.5 (Semantic Diff).
 *
 * Renders a structured diff between two git revisions, showing
 * flows/resources/tests added/modified/removed in human-readable form.
 */

import type { StructuredDiff } from './api';

interface DiffViewerProps {
  diff: StructuredDiff;
}

export function DiffViewer({ diff }: DiffViewerProps) {
  if (diff.total_changes === 0) {
    return (
      <div className="diff-viewer">
        <div className="diff-viewer__header">
          <span className="diff-viewer__range">
            {diff.base_sha} → {diff.head_sha}
          </span>
          <span className="badge badge--success">no changes</span>
        </div>
        <p className="muted">No changes between these revisions.</p>
      </div>
    );
  }

  return (
    <div className="diff-viewer">
      <div className="diff-viewer__header">
        <span className="diff-viewer__range">
          {diff.base_sha} → {diff.head_sha}
        </span>
        <span className="badge badge--info">{diff.total_changes} change(s)</span>
      </div>

      <DiffSection title="Flows" data={diff.flows} />
      <DiffSection title="Resources" data={diff.resources} />
      <DiffSection title="Tests" data={diff.tests} />

      {diff.other.length > 0 && (
        <div className="diff-section">
          <h4 className="diff-section__title">Other</h4>
          <ul className="diff-list">
            {diff.other.map((entry, i) => (
              <li key={i} className={`diff-item diff-item--${entry.status}`}>
                <span className="diff-item__symbol">
                  {entry.status === 'added' ? '+' : entry.status === 'removed' ? '-' : entry.status === 'renamed' ? 'R' : '~'}
                </span>
                <span className="diff-item__path">{entry.path}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="diff-viewer__footer">
        <p className="muted">Run Validate + Run Tests for full review.</p>
      </div>
    </div>
  );
}

function DiffSection({
  title,
  data,
}: {
  title: string;
  data: { added: string[]; modified: string[]; removed: string[] };
}) {
  const total = data.added.length + data.modified.length + data.removed.length;
  if (total === 0) return null;

  return (
    <div className="diff-section">
      <h4 className="diff-section__title">
        {title}
        <span className="badge badge--mono">{total}</span>
      </h4>
      <ul className="diff-list">
        {data.added.map((path, i) => (
          <li key={`a${i}`} className="diff-item diff-item--added">
            <span className="diff-item__symbol">+</span>
            <span className="diff-item__path">{path}</span>
          </li>
        ))}
        {data.modified.map((path, i) => (
          <li key={`m${i}`} className="diff-item diff-item--modified">
            <span className="diff-item__symbol">~</span>
            <span className="diff-item__path">{path}</span>
          </li>
        ))}
        {data.removed.map((path, i) => (
          <li key={`r${i}`} className="diff-item diff-item--removed">
            <span className="diff-item__symbol">-</span>
            <span className="diff-item__path">{path}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
