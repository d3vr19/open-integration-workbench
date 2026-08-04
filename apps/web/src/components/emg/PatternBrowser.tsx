/** PatternBrowser — browse all approved EMG insights. WP-06 E-003. */

interface Insight {
  id: string;
  taskId: string;
  confidence: number;
  supportCount: number;
  workflowStepCount: number;
  correctionCount: number;
}

export function PatternBrowser({ insights, onClose }: { insights: Insight[]; onClose: () => void }) {
  return (
    <div className="pattern-browser">
      <div className="pattern-browser__header">
        <h4 className="pattern-browser__title">All Patterns ({insights.length})</h4>
        <button className="pattern-browser__close" onClick={onClose}>×</button>
      </div>
      <div className="pattern-browser__list">
        {insights.map(insight => (
          <div key={insight.id} className="pattern-browser__item">
            <span className="pattern-browser__name">{insight.taskId}</span>
            <span className="badge badge--mono">{Math.round(insight.confidence * 100)}%</span>
            <span className="badge badge--mono">×{insight.supportCount}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
