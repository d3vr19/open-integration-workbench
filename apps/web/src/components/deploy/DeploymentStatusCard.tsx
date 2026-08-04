/** DeploymentStatusCard — current state + history. WP-06 E-002. */

interface DeployState {
  current: string;
  history: Array<{ from_state: string; to_state: string; timestamp: string; actor: string; evidence: Record<string, unknown> }>;
}

export function DeploymentStatusCard({ state }: { state: DeployState }) {
  return (
    <div className="deploy-status">
      <div className="deploy-status__current">
        <span className="deploy-status__label">Current:</span>
        <span className="badge badge--info">{state.current}</span>
      </div>
      {state.history.length > 0 && (
        <div className="deploy-history">
          <span className="deploy-history__label">History ({state.history.length}):</span>
          {state.history.slice(-3).map((h, i) => (
            <div key={i} className="deploy-history__item">
              <span className="deploy-history__transition">{h.from_state} → {h.to_state}</span>
              <span className="deploy-history__actor">{h.actor}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
