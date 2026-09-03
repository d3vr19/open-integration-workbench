import { useEffect, useState } from 'react';
import { api } from '../../api';
import type { ExperimentSummary, ExperimentRecord } from '../../api';

export function ExperimentsPanel() {
  const [summaries, setSummaries] = useState<ExperimentSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selectedRecord, setSelectedRecord] = useState<ExperimentRecord | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    api.listExperiments()
      .then((data) => {
        setSummaries(data);
        if (data.length > 0) {
          setSelectedId(data[0].experimentId ?? null);
        }
      })
      .catch((err) => {
        setError(err instanceof Error ? err.message : 'Failed to load experiments');
      })
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (!selectedId) {
      setSelectedRecord(null);
      return;
    }
    api.getExperiment(selectedId)
      .then(setSelectedRecord)
      .catch((err) => {
        setError(err instanceof Error ? err.message : 'Failed to load campaign record');
      });
  }, [selectedId]);

  return (
    <div className="experiments-panel" data-testid="experiments-panel">
      <div className="experiments-panel__header">
        <h3 className="experiments-panel__title" data-testid="experiments-panel-title">
          B2 Experiments
        </h3>
        {summaries.length > 0 && (
          <span className="badge badge--mono" data-testid="experiments-count-badge">
            {summaries.length} {summaries.length === 1 ? 'campaign' : 'campaigns'}
          </span>
        )}
      </div>

      {loading && <div className="muted" data-testid="experiments-loading">Loading campaigns...</div>}
      {error && (
        <div className="error-banner--inline" data-testid="experiments-error">
          {error}
          <button className="btn-link" onClick={() => setError(null)}>dismiss</button>
        </div>
      )}

      {!loading && !error && summaries.length === 0 && (
        <div className="muted" data-testid="experiments-empty">
          No experiment campaigns recorded yet.
        </div>
      )}

      {summaries.length > 0 && (
        <div className="campaign-selector" data-testid="experiment-campaign-list">
          {summaries.map((s) => (
            <div
              key={s.experimentId}
              className={`campaign-card ${selectedId === s.experimentId ? 'campaign-card--active' : ''}`}
              onClick={() => setSelectedId(s.experimentId ?? null)}
              data-testid={`campaign-item-${s.experimentId}`}
            >
              <div className="campaign-card__header">
                <span className="campaign-card__id" data-testid="experiment-id">{s.experimentId}</span>
                <span
                  className={`badge ${s.baselineVerdict === 'GREEN' ? 'badge--success' : s.baselineVerdict === 'RED' ? 'badge--error' : 'badge--mono'}`}
                  data-testid="baseline-verdict-badge"
                >
                  {s.baselineVerdict}
                </span>
              </div>
              <div className="campaign-card__baseline muted">
                flow: {s.baselineFlowId || 'unknown'}
              </div>
              <div className="campaign-card__tallies" data-testid="verdict-tallies">
                <span className="tally-item" data-testid="tally-total" title="Total rungs">
                  {s.rungCount} rungs
                </span>
                <span className="tally-item tally-item--green" data-testid="tally-green" title="Green rungs">
                  {s.greenCount} green
                </span>
                <span className="tally-item tally-item--red" data-testid="tally-red" title="Red rungs">
                  {s.redCount} red
                </span>
                {(s.skippedCount ?? 0) > 0 && (
                  <span className="tally-item tally-item--skipped" data-testid="tally-skipped" title="Skipped rungs">
                    {s.skippedCount} skipped
                  </span>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {selectedRecord && (
        <div className="campaign-detail" data-testid="experiment-detail">
          <div className="campaign-detail__meta">
            {selectedRecord.hypothesis && (
              <p className="campaign-detail__hypothesis">
                <strong>Hypothesis:</strong> {selectedRecord.hypothesis}
              </p>
            )}
            {selectedRecord.createdAt && (
              <span className="campaign-detail__date muted">
                {new Date(selectedRecord.createdAt).toLocaleString()}
              </span>
            )}
          </div>

          <h4 className="campaign-detail__subhead">Rungs ({selectedRecord.rungs?.length ?? 0})</h4>
          <div className="rungs-list" data-testid="rungs-list">
            {(selectedRecord.rungs ?? []).map((r) => (
              <div key={r.rungId} className="rung-card" data-testid={`rung-card-${r.rungId}`}>
                <div className="rung-card__top">
                  <code className="rung-card__id" data-testid="rung-id">{r.rungId}</code>
                  <span
                    className={`badge ${r.verdict === 'GREEN' ? 'badge--success' : r.verdict === 'RED' ? 'badge--error' : 'badge--mono'}`}
                    data-testid="rung-verdict"
                  >
                    {r.verdict}
                  </span>
                </div>
                <div className="rung-card__action">
                  <span className="badge badge--mono">{r.kind}</span>
                  <span className="rung-card__target">{r.target}</span>
                  {r.detail && Object.keys(r.detail).length > 0 && (
                    <span className="muted">({JSON.stringify(r.detail)})</span>
                  )}
                </div>
                {r.rationale && (
                  <div className="rung-card__rationale muted">{r.rationale}</div>
                )}
                {r.evidence && Object.keys(r.evidence).length > 0 && (
                  <div className="rung-card__evidence" data-testid="rung-evidence">
                    {Boolean(r.evidence.targetType) && (
                      <span className="evidence-chip" data-testid="evidence-target-type">
                        target: {String(r.evidence.targetType)}
                      </span>
                    )}
                    {r.evidence.httpResponseStatus != null && (
                      <span className="evidence-chip">
                        HTTP {String(r.evidence.httpResponseStatus)}
                      </span>
                    )}
                    {Boolean(r.evidence.finalStatus) && (
                      <span className="evidence-chip">
                        {String(r.evidence.finalStatus)}
                      </span>
                    )}
                    {Array.isArray(r.evidence.mplStatuses) && (
                      <span className="evidence-chip">
                        MPL: {r.evidence.mplStatuses.join(', ')}
                      </span>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
