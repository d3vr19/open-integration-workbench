import { useEffect, useState } from 'react';
import { api } from '../../api';
import type { LawRecord } from '../../api';

export function LawRegistryPanel() {
  const [laws, setLaws] = useState<LawRecord[]>([]);
  const [statusFilter, setStatusFilter] = useState<'all' | 'ratified' | 'candidate' | 'retired'>('all');
  const [scopeFilter, setScopeFilter] = useState<string>('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    const filterParam = statusFilter === 'all' ? undefined : statusFilter;
    api.listLaws({ status: filterParam, scope: scopeFilter || undefined })
      .then(setLaws)
      .catch((err) => {
        setError(err instanceof Error ? err.message : 'Failed to load laws');
      })
      .finally(() => setLoading(false));
  }, [statusFilter, scopeFilter]);

  return (
    <div className="law-registry-panel" data-testid="law-registry-panel">
      <div className="law-registry-panel__header">
        <h3 className="law-registry-panel__title" data-testid="law-registry-title">
          Law Registry
        </h3>
        <span className="badge badge--mono" data-testid="law-count-badge">
          {laws.length} {laws.length === 1 ? 'law' : 'laws'}
        </span>
      </div>

      <div className="law-registry-panel__filters" data-testid="laws-filter">
        <div className="status-filter-group">
          {(['all', 'ratified', 'candidate', 'retired'] as const).map((st) => (
            <button
              key={st}
              className={`btn-chip ${statusFilter === st ? 'btn-chip--active' : ''}`}
              onClick={() => setStatusFilter(st)}
              data-testid={`filter-status-${st}`}
            >
              {st}
            </button>
          ))}
        </div>
        {scopeFilter ? (
          <div className="scope-active-filter">
            <span>scope: {scopeFilter}</span>
            <button className="btn-link" onClick={() => setScopeFilter('')}>clear</button>
          </div>
        ) : null}
      </div>

      {loading && <div className="muted" data-testid="laws-loading">Loading laws...</div>}
      {error && (
        <div className="error-banner--inline" data-testid="laws-error">
          {error}
          <button className="btn-link" onClick={() => setError(null)}>dismiss</button>
        </div>
      )}

      {!loading && !error && laws.length === 0 && (
        <div className="muted" data-testid="laws-empty">
          No laws found for selected filter.
        </div>
      )}

      <div className="laws-list" data-testid="laws-list">
        {laws.map((law) => (
          <div key={law.lawId} className="law-card" data-testid={`law-card-${law.lawId}`}>
            <div className="law-card__header">
              <div className="law-card__chips">
                <span
                  className={`badge ${law.status === 'ratified' ? 'badge--success' : law.status === 'candidate' ? 'badge--warn' : 'badge--mono'}`}
                  data-testid="law-status"
                >
                  {law.status}
                </span>
                <span
                  className={`badge ${law.source === 'engine' ? 'badge--mono' : 'badge--info'}`}
                  data-testid="law-source"
                >
                  {law.source}
                </span>
                {law.confidence != null && (
                  <span className="law-confidence" data-testid="law-confidence">
                    conf: {Math.round((law.confidence ?? 0) * 100)}%
                  </span>
                )}
              </div>
              <code className="law-card__id" data-testid="law-id">{law.lawId}</code>
            </div>

            <p className="law-card__statement" data-testid="law-statement">
              {law.statement}
            </p>

            <div className="law-card__scope-line">
              <span className="properties__label">Scope:</span>{' '}
              <button
                className="scope-tag"
                onClick={() => setScopeFilter(law.scope || '')}
                data-testid="law-scope"
                title="Filter by this scope"
              >
                {law.scope}
              </button>
              {law.origin && (
                <span className="muted law-origin" data-testid="law-origin">
                  from: {law.origin}
                </span>
              )}
            </div>

            {law.evidence && (
              <div className="law-evidence" data-testid="law-evidence">
                {Array.isArray(law.evidence.greenRungs) && law.evidence.greenRungs.length > 0 && (
                  <div className="evidence-row">
                    <span className="evidence-label green">green rungs:</span>
                    {law.evidence.greenRungs.map((r, i) => (
                      <code key={i} className="evidence-rung evidence-rung--green">{r}</code>
                    ))}
                  </div>
                )}
                {Array.isArray(law.evidence.redRungs) && law.evidence.redRungs.length > 0 && (
                  <div className="evidence-row">
                    <span className="evidence-label red">red rungs:</span>
                    {law.evidence.redRungs.map((r, i) => (
                      <code key={i} className="evidence-rung evidence-rung--red">{r}</code>
                    ))}
                  </div>
                )}
              </div>
            )}

            {law.predicate ? (
              <div className="predicate-box" data-testid="law-predicate">
                <div className="predicate-box__title">Machine Predicate:</div>
                <div className="predicate-box__type">{String(law.predicate.type || 'rule')}</div>
                {law.predicate.node ? (
                  <div>node: <code>{String(law.predicate.node)}</code></div>
                ) : null}
                {Array.isArray(law.predicate.redPositions) ? (
                  <div>red positions: <code>[{(law.predicate.redPositions as unknown[]).join(', ')}]</code></div>
                ) : null}
                {Array.isArray(law.predicate.greenPositions) ? (
                  <div>green positions: <code>[{(law.predicate.greenPositions as unknown[]).join(', ')}]</code></div>
                ) : null}
              </div>
            ) : (
              <div className="muted predicate-box--advisory" data-testid="law-predicate-advisory">
                Advisory-only (no machine predicate)
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
