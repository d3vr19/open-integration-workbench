/** InsightCard — individual EMG insight display. WP-06 E-003. */

interface Insight {
  id: string;
  taskId: string;
  confidence: number;
  supportCount: number;
  workflowStepCount: number;
  correctionCount: number;
  provenance: Record<string, unknown> | null;
}

interface InsightCardProps {
  insight: Insight;
  /** WP-08 PR-10: clicking the card toggles the TrajectoryViewer below it. */
  expanded?: boolean;
  onToggle?: () => void;
}

export function InsightCard({ insight, expanded = false, onToggle }: InsightCardProps) {
  const confPct = Math.round(insight.confidence * 100);
  const confColor = confPct >= 80 ? 'var(--oiw-success)' : confPct >= 50 ? 'var(--oiw-warning)' : 'var(--oiw-error)';

  return (
    <div className={`insight-card ${expanded ? 'insight-card--expanded' : ''}`}>
      <div
        className="insight-card__header"
        onClick={onToggle}
        role="button"
        tabIndex={0}
        aria-expanded={expanded}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            onToggle?.();
          }
        }}
      >
        <span className="insight-card__name">{insight.taskId}</span>
        <span className="insight-card__support" title="Support count (times reused)">
          ×{insight.supportCount}
        </span>
      </div>
      <div className="insight-card__confidence">
        <div className="insight-card__bar-bg">
          <div className="insight-card__bar-fill" style={{ width: `${confPct}%`, background: confColor }} />
        </div>
        <span className="insight-card__conf-value" style={{ color: confColor }}>{confPct}%</span>
      </div>
      <div className="insight-card__meta">
        <span className="badge badge--mono">{insight.workflowStepCount} steps</span>
        {insight.correctionCount > 0 && (
          <span className="badge badge--warn">{insight.correctionCount} corrections</span>
        )}
      </div>
      {insight.provenance && (
        <div className="insight-card__provenance" title="Provenance">
          <span className="insight-card__prov-label">from:</span>
          <span className="insight-card__prov-value">{String(insight.provenance?.matchStage || 'exact')}</span>
        </div>
      )}
    </div>
  );
}
