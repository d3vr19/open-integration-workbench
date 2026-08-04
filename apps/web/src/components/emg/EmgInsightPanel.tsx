/**
 * EmgInsightPanel — shows EMG insights + mechanics-first indicator.
 * WP-06 Track E Task E-003.
 */
import { useEffect, useState } from 'react';
import { InsightCard } from './InsightCard';
import { PatternBrowser } from './PatternBrowser';

interface EmgInsight {
  id: string;
  taskId: string;
  confidence: number;
  supportCount: number;
  workflowStepCount: number;
  correctionCount: number;
  provenance: Record<string, unknown> | null;
  approval: string;
}

interface EmgStats {
  totalTrajectories: number;
  approvedInsights: number;
  crossTaskEdges: number;
  retrievalHitRate: number;
  adapterFamilies: string[];
}

interface EmgInsightPanelProps {
  projectId: string | null;
  emgUsed: boolean;
}

export function EmgInsightPanel({ projectId, emgUsed }: EmgInsightPanelProps) {
  const [insights, setInsights] = useState<EmgInsight[]>([]);
  const [stats, setStats] = useState<EmgStats | null>(null);
  const [loading, setLoading] = useState(false);
  const [showBrowser, setShowBrowser] = useState(false);

  useEffect(() => {
    if (!projectId) return;
    setLoading(true);
    Promise.all([
      fetch(`/api/v1/projects/${projectId}/emg/insights`).then(r => r.json()).catch(() => []),
      fetch(`/api/v1/emg/stats`).then(r => r.json()).catch(() => null),
    ]).then(([ins, st]) => {
      setInsights(ins);
      setStats(st);
      setLoading(false);
    });
  }, [projectId]);

  return (
    <div className="emg-panel">
      <div className="emg-panel__header">
        <h3 className="emg-panel__title">EMG Insights</h3>
        {emgUsed && (
          <span className="emg-badge emg-badge--hit" title="Mechanics-first: EMG provided the plan, 0 LLM tokens used">
            ⚡ EMG hit
          </span>
        )}
      </div>

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
        </div>
      )}

      {loading && <div className="emg-panel__loading">Loading insights…</div>}

      {!loading && insights.length === 0 && (
        <p className="muted">No EMG insights found. Run the seed corpus to populate.</p>
      )}

      {!loading && insights.length > 0 && !showBrowser && (
        <div className="emg-insight-list">
          {insights.slice(0, 3).map(insight => (
            <InsightCard key={insight.id} insight={insight} />
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
