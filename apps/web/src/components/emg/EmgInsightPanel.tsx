/**
 * EmgInsightPanel — shows EMG insights + mechanics-first indicator.
 * WP-06 Track E Task E-003.
 * WP-08 PR-10 / OW-032: reads the durable store via typed API calls,
 * surfaces the embedding backend/compatibility chips, and renders the
 * ⚡ EMG-hit badge from REAL agent-response metadata (`emgHit` prop) —
 * never a hardcoded value.
 */
import { useEffect, useState } from 'react';
import { api } from '../../api';
import type { EmgHit, EmgInsightSummary, EmgStats } from '../../api';
import { InsightCard } from './InsightCard';
import { PatternBrowser } from './PatternBrowser';
import { TrajectoryViewer } from './TrajectoryViewer';

interface EmgInsightPanelProps {
  projectId: string | null;
  /** Truthful retrieval metadata from the last agents:plan/implement call. */
  emgHit?: EmgHit | null;
}

export function EmgInsightPanel({ projectId, emgHit }: EmgInsightPanelProps) {
  const [insights, setInsights] = useState<EmgInsightSummary[]>([]);
  const [stats, setStats] = useState<EmgStats | null>(null);
  const [loading, setLoading] = useState(false);
  const [showBrowser, setShowBrowser] = useState(false);
  const [openInsightId, setOpenInsightId] = useState<string | null>(null);

  useEffect(() => {
    if (!projectId) return;
    setLoading(true);
    Promise.all([
      api.emgInsights(projectId).catch(() => []),
      api.emgStats().catch(() => null),
    ]).then(([ins, st]) => {
      setInsights(ins);
      setStats(st);
      setLoading(false);
    });
  }, [projectId]);

  const emgUsed = emgHit?.used === true;

  return (
    <div className="emg-panel">
      <div className="emg-panel__header">
        <h3 className="emg-panel__title">EMG Insights</h3>
        {emgUsed && (
          <span
            className="emg-badge emg-badge--hit"
            title={`Mechanics-first: EMG provided a matched expert pattern (confidence ${Math.round((emgHit?.confidence ?? 0) * 100)}%), no LLM tokens needed`}
            data-testid="emg-hit-badge"
          >
            ⚡ EMG hit
          </span>
        )}
      </div>

      {/* OW-032: truthful retrieval metadata from the last agent round-trip */}
      {emgUsed && (
        <div className="emg-hits" data-testid="emg-hit-details">
          <span className="emg-hits__confidence">
            {(emgHit?.confidence ?? 0).toFixed(2)}
          </span>
          {emgHit?.taskId && <code className="emg-hits__task">{emgHit.taskId}</code>}
          {emgHit?.provenance?.matchStage && (
            <span className="badge badge--mono">{emgHit.provenance.matchStage}</span>
          )}
        </div>
      )}

      {stats && (
        <div className="emg-stats">
          <span className="emg-stats__item" title="Total trajectories in corpus">{stats.totalTrajectories} trajectories</span>
          <span className="emg-stats__item" title="Approved insights">{stats.approvedInsights} insights</span>
          {stats.crossTaskEdges > 0 && (
            <span className="emg-stats__item" title="Cross-task edges">{stats.crossTaskEdges} edges</span>
          )}
          {stats.retrievalHitRate > 0 && (
            <span className="emg-stats__item" title="Retrieval hit rate">{(stats.retrievalHitRate * 100).toFixed(0)}% hit</span>
          )}
          {/* WP-08 A-003: real embedding config — honesty chips */}
          {stats.embeddingBackend && (
            <span
              className="emg-stats__backend"
              data-testid="emg-backend-chip"
              title={`Embeddings: ${stats.embeddingBackend} / ${stats.embeddingModel || '?'} @ dim ${stats.embeddingDim}`}
            >
              {stats.embeddingBackend}
              {stats.embeddingDim ? `·${stats.embeddingDim}` : ''}
              {stats.compatible ? ' ✓' : ' ⚠'}
            </span>
          )}
        </div>
      )}

      {loading && <div className="emg-panel__loading">Loading insights…</div>}

      {!loading && insights.length === 0 && (
        <p className="muted">No EMG insights found. Run the seed corpus to populate.</p>
      )}

      {!loading && insights.length > 0 && !showBrowser && (
        <div className="emg-insight-list">
          {insights.slice(0, 3).map(insight => (
            <div key={insight.id}>
              <InsightCard
                insight={insight}
                expanded={openInsightId === insight.id}
                onToggle={() =>
                  setOpenInsightId(openInsightId === insight.id ? null : insight.id)
                }
              />
              {openInsightId === insight.id && <TrajectoryViewer insightId={insight.id} />}
            </div>
          ))}
          {insights.length > 3 && (
            <button className="emg-panel__more" onClick={() => setShowBrowser(true)}>
              View all {insights.length} patterns →
            </button>
          )}
        </div>
      )}

      {showBrowser && (
        <PatternBrowser insights={insights} onClose={() => setShowBrowser(false)} />
      )}
    </div>
  );
}
