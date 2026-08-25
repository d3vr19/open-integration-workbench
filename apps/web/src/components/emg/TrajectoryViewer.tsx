/**
 * TrajectoryViewer — expandable expert-workflow details for one insight.
 * WP-06 E-003 stub; finished in WP-08 PR-10 / OW-032: fetches the real
 * insight detail from GET /emg/insights/{id} instead of a placeholder.
 */
import { useEffect, useState } from 'react';
import { api } from '../../api';
import type { EmgInsightDetail } from '../../api';

interface TrajectoryViewerProps {
  insightId: string;
}

export function TrajectoryViewer({ insightId }: TrajectoryViewerProps) {
  const [detail, setDetail] = useState<EmgInsightDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (!open || detail || error) return;
    let cancelled = false;
    api
      .emgInsightDetail(insightId)
      .then((d) => {
        if (!cancelled) setDetail(d);
      })
      .catch((e) => {
        if (!cancelled) setError(String(e));
      });
    return () => {
      cancelled = true;
    };
  }, [open, detail, error, insightId]);

  return (
    <div className="trajectory-viewer" data-insight-id={insightId}>
      <button className="trajectory-viewer__summary" onClick={() => setOpen((o) => !o)}>
        {open ? '▾' : '▸'} View trajectory details
      </button>
      {open && (
        <div className="trajectory-viewer__body">
          {error && <p className="trajectory-viewer__error">{error}</p>}
          {!error && !detail && <p className="muted">Loading…</p>}
          {detail && (
            <>
              <div className="trajectory-viewer__section">
                <span className="trajectory-viewer__label">Expert workflow</span>
                <ol className="trajectory-viewer__steps">
                  {detail.successfulWorkflow.length === 0 && (
                    <li className="muted">No recorded workflow.</li>
                  )}
                  {detail.successfulWorkflow.map((step, i) => {
                    const action = Array.isArray(step.action) ? step.action : [];
                    const tool = String(action[0] ?? 'unknown');
                    const op = String(action[1] ?? '');
                    const component = String(action[2] ?? '');
                    return (
                      <li key={i} className="trajectory-viewer__step">
                        <span className="badge badge--mono">{tool}</span>{' '}
                        {component ? (
                          <code className="trajectory-viewer__component">{op} {component}</code>
                        ) : (
                          <code>{op}</code>
                        )}
                      </li>
                    );
                  })}
                </ol>
              </div>
              <div className="trajectory-viewer__section">
                <span className="trajectory-viewer__label">Corrections</span>
                {detail.corrections.length === 0 ? (
                  <p className="muted">None — pure expert trajectory.</p>
                ) : (
                  <ul className="trajectory-viewer__corrections">
                    {detail.corrections.map((c, i) => (
                      <li key={i}>
                        avoid{' '}
                        <code>
                          {JSON.stringify(c.avoid ?? c.trigger ?? {}).slice(0, 120)}
                        </code>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}
