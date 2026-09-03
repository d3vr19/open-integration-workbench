import { useEffect, useState, useMemo } from 'react';
import { api } from '../../api';
import type { CalibrationReport, CalibrationSummary, SimulationResult } from '../../api';

interface TenantMplComparisonProps {
  projectId: string | null;
  flowId: string | null;
  simulation: SimulationResult | null;
  onClose: () => void;
}

function parseLogStartMs(raw?: string): number | null {
  if (!raw) return null;
  const match = raw.match(/\((\d+)\)/);
  if (match) return Number(match[1]);
  const parsed = Date.parse(raw);
  return isNaN(parsed) ? null : parsed;
}

export function TenantMplComparison({
  projectId,
  flowId,
  simulation,
  onClose,
}: TenantMplComparisonProps) {
  const [calibrations, setCalibrations] = useState<CalibrationSummary[]>([]);
  const [selectedArtifactId, setSelectedArtifactId] = useState<string | null>(null);
  const [report, setReport] = useState<CalibrationReport | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!projectId) return;
    setLoading(true);
    setError(null);
    api.listCalibrations(projectId)
      .then((summaries) => {
        setCalibrations(summaries);
        if (summaries.length > 0) {
          // Prefer artifact matching flowId if present, else first
          const match = summaries.find((s) => s.artifactId === flowId) || summaries[0];
          setSelectedArtifactId(match.artifactId ?? null);
        }
      })
      .catch((err) => {
        setError(err instanceof Error ? err.message : 'Failed to list calibrations');
      })
      .finally(() => setLoading(false));
  }, [projectId, flowId]);

  useEffect(() => {
    if (!projectId || !selectedArtifactId) {
      setReport(null);
      return;
    }
    setLoading(true);
    api.getCalibration(projectId, selectedArtifactId)
      .then(setReport)
      .catch((err) => {
        setError(err instanceof Error ? err.message : 'Failed to fetch calibration report');
      })
      .finally(() => setLoading(false));
  }, [projectId, selectedArtifactId]);

  const startedAtMs = useMemo(() => {
    const started = report?.calibration?.startedAt;
    if (!started) return null;
    const ms = Date.parse(started);
    return isNaN(ms) ? null : ms;
  }, [report]);

  return (
    <div className="mpl-comparison" data-testid="mpl-comparison-view">
      <div className="mpl-comparison__header">
        <h3 className="mpl-comparison__title">
          Tenant-MPL Comparison View (B-003)
        </h3>
        <button className="btn-secondary" onClick={onClose} data-testid="mpl-close-btn">
          Close
        </button>
      </div>

      {loading && <div className="muted" data-testid="mpl-loading">Loading calibration data...</div>}
      {error && (
        <div className="error-banner--inline" data-testid="mpl-error">
          {error}
          <button className="btn-link" onClick={() => setError(null)}>dismiss</button>
        </div>
      )}

      {calibrations.length > 1 && (
        <div className="mpl-comparison__artifact-selector">
          <span className="properties__label">Artifact:</span>
          {calibrations.map((c) => (
            <button
              key={c.artifactId}
              className={`btn-chip ${selectedArtifactId === c.artifactId ? 'btn-chip--active' : ''}`}
              onClick={() => setSelectedArtifactId(c.artifactId ?? null)}
            >
              {c.artifactId}
            </button>
          ))}
        </div>
      )}

      <div className="mpl-comparison__grid">
        {/* LEFT COLUMN: LOCAL SIMULATION TRACE */}
        <div className="mpl-column mpl-column--local" data-testid="mpl-col-local">
          <div className="mpl-column__header">
            <h4>Local Simulation Trace</h4>
            {simulation && (
              <span
                className={`badge ${simulation.status === 'COMPLETED' ? 'badge--success' : 'badge--error'}`}
                data-testid="local-status-badge"
              >
                {simulation.status}
              </span>
            )}
          </div>
          {simulation ? (
            <div className="mpl-local-trace">
              <div className="mpl-meta-row">
                <span className="properties__label">Duration:</span>{' '}
                <span className="badge badge--mono">{simulation.duration_ms}ms</span>
                <span className="properties__label" style={{ marginLeft: 8 }}>Steps:</span>{' '}
                <span className="badge badge--mono">{simulation.trace.length}</span>
              </div>
              <div className="trace-list">
                {simulation.trace.map((t, i) => (
                  <div key={i} className={`trace-item trace-item--${t.direction}`}>
                    <span className="trace-item__node">{t.node_id}</span>
                    <span className="trace-item__direction">{t.direction}</span>
                    <span className="trace-item__summary">{t.summary}</span>
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <div className="muted" data-testid="mpl-no-sim">
              No active simulation. Run a simulation to compare local trace against tenant MPL.
            </div>
          )}
        </div>

        {/* RIGHT COLUMN: CACHED TENANT MPL ROWS */}
        <div className="mpl-column mpl-column--tenant" data-testid="mpl-col-tenant">
          <div className="mpl-column__header">
            <h4>Cached Tenant Oracle (MPL)</h4>
            {report?.calibration?.finalStatus && (
              <span
                className={`badge ${report.calibration.finalStatus === 'STARTED' ? 'badge--success' : 'badge--error'}`}
                data-testid="tenant-final-status"
              >
                {report.calibration.finalStatus}
              </span>
            )}
          </div>

          {report?.calibration ? (
            <div className="mpl-tenant-report">
              <div className="mpl-meta-row">
                {report.calibration.artifactId && (
                  <span><strong>Artifact:</strong> <code>{report.calibration.artifactId}</code></span>
                )}
                {report.calibration.httpResponseStatus != null && (
                  <span><strong>HTTP:</strong> <span className="badge badge--mono">{report.calibration.httpResponseStatus}</span></span>
                )}
                {report.reward?.overall != null && (
                  <span data-testid="mpl-reward-score">
                    <strong>Reward:</strong> <span className="badge badge--success">{Math.round(report.reward.overall * 100)}%</span>
                  </span>
                )}
              </div>

              {report.calibration.startedAt && (
                <div className="epoch-boundary-box" data-testid="mpl-epoch-boundary">
                  <span className="properties__label">Epoch Boundary (startedAt):</span>{' '}
                  <code>{report.calibration.startedAt}</code>
                  <div className="muted" style={{ fontSize: '0.8rem', marginTop: 4 }}>
                    Epoch honesty: only MPL rows at or after this instant belong to this run.
                  </div>
                </div>
              )}

              <h5 className="mpl-rows-heading">
                MPL Rows ({report.calibration.mplRows?.length ?? 0})
              </h5>
              <div className="mpl-rows-list" data-testid="mpl-rows-table">
                {(report.calibration.mplRows ?? []).map((row, i) => {
                  const rowMs = parseLogStartMs(row.LogStart);
                  const isCurrent = startedAtMs != null && rowMs != null
                    ? rowMs >= startedAtMs - 1000
                    : true;

                  return (
                    <div
                      key={row.MessageGuid || i}
                      className={`mpl-row-card ${isCurrent ? 'mpl-row-card--current' : 'mpl-row-card--stale'}`}
                      data-testid={isCurrent ? 'mpl-row-current' : 'mpl-row-stale'}
                    >
                      <div className="mpl-row-card__top">
                        <code className="mpl-row-card__guid">{row.MessageGuid || `row-${i}`}</code>
                        <span
                          className={`badge ${row.Status === 'COMPLETED' ? 'badge--success' : 'badge--error'}`}
                          data-testid="mpl-row-status"
                        >
                          {row.Status}
                        </span>
                        <span
                          className={`badge ${isCurrent ? 'badge--info' : 'badge--warn'}`}
                          data-testid="mpl-epoch-tag"
                        >
                          {isCurrent ? 'this run' : 'prior epoch'}
                        </span>
                      </div>
                      <div className="mpl-row-card__meta muted">
                        {row.IntegrationFlowName && <span>flow: {row.IntegrationFlowName} | </span>}
                        <span>LogStart: {row.LogStart}</span>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          ) : (
            <div className="muted" data-testid="mpl-no-report">
              {!loading && !error && (
                <p>
                  No cached calibration report found for project '{projectId}'. Calibrations are produced by the CLI oracle loop (<code>oiw tenant calibrate</code>).
                </p>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
