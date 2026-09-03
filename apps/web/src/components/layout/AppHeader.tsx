import type { GitStatus } from '../../api';

interface AppHeaderProps {
  dirty: boolean;
  pendingOpsCount: number;
  loading: boolean;
  onSave: () => void;
  gitStatus: GitStatus | null;
}

export function AppHeader({ dirty, pendingOpsCount, loading, onSave, gitStatus }: AppHeaderProps) {
  return (
    <header className="app__header">
      <div className="app__brand">
        <span className="app__logo">OIW</span>
        <span className="app__title">Open Integration Workbench</span>
      </div>
      <div className="app__header-actions">
        {dirty && (
          <span className="badge badge--warn">unsaved changes ({pendingOpsCount})</span>
        )}
        {dirty && (
          <button onClick={onSave} disabled={loading} className="btn btn--primary btn--sm">
            Save
          </button>
        )}
        {gitStatus && (
          <div className="app__git-status">
            <span className="badge badge--info">{gitStatus.branch}</span>
            <span className="badge badge--mono">{gitStatus.head_sha}</span>
            {gitStatus.dirty && <span className="badge badge--warn">dirty</span>}
            {gitStatus.last_build_digest && (
              <span className="badge badge--success badge--mono">
                {gitStatus.last_build_digest.slice(0, 12)}
              </span>
            )}
          </div>
        )}
      </div>
    </header>
  );
}
