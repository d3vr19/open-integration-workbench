/** DeployPanel — deployment state machine UI. WP-06 Track E Task E-002. */
import { useEffect, useState } from 'react';
import { DeploymentStatusCard } from './DeploymentStatusCard';
import { DriftReportDialog } from './DriftReportDialog';
import { ApprovalDialog } from './ApprovalDialog';

interface DeployState {
  current: string;
  history: Array<{ from_state: string; to_state: string; timestamp: string; actor: string; evidence: Record<string, unknown> }>;
}

interface DriftReport {
  status: string;
  safeToUpload: boolean;
  localDigest?: string;
  tenantDigest?: string;
  recommendation?: string;
}

interface DeployPanelProps {
  projectId: string | null;
}

const STATES = ['DRAFT', 'VALIDATED', 'TESTED', 'BUILT', 'PROPOSED', 'APPROVED', 'UPLOADED', 'DEPLOYED', 'VERIFIED'];

export function DeployPanel({ projectId }: DeployPanelProps) {
  const [profile, setProfile] = useState('dev');
  const [state, setState] = useState<DeployState | null>(null);
  const [drift, setDrift] = useState<DriftReport | null>(null);
  const [loading, setLoading] = useState(false);
  const [showApproval, setShowApproval] = useState(false);

  const fetchState = () => {
    if (!projectId) return;
    setLoading(true);
    fetch(`/api/v1/projects/${projectId}/deployments/${profile}/status`)
      .then(r => r.ok ? r.json() : null)
      .then(s => setState(s))
      .catch(() => setState(null))
      .finally(() => setLoading(false));
  };

  const checkDrift = () => {
    if (!projectId) return;
    fetch(`/api/v1/projects/${projectId}/deployments/${profile}/drift`)
      .then(r => r.ok ? r.json() : null)
      .then(d => setDrift(d))
      .catch(() => setDrift(null));
  };

  useEffect(() => { fetchState(); }, [projectId, profile]);

  const currentIndex = state ? STATES.indexOf(state.current) : -1;

  return (
    <div className="deploy-panel">
      <div className="deploy-panel__header">
        <h3 className="deploy-panel__title">Deployment</h3>
        <select className="deploy-panel__profile" value={profile} onChange={e => setProfile(e.target.value)}>
          <option value="dev">dev</option>
          <option value="test">test</option>
          <option value="prod">prod</option>
        </select>
      </div>

      {state && (
        <div className="deploy-state-machine">
          {STATES.map((s, i) => (
            <div key={s} className={`deploy-state-node ${i === currentIndex ? 'deploy-state-node--current' : ''} ${i < currentIndex ? 'deploy-state-node--done' : ''}`}>
              <span className="deploy-state-node__label">{s}</span>
            </div>
          ))}
        </div>
      )}

      {drift && !drift.safeToUpload && (
        <div className="deploy-drift-warning">
          ⚠ Drift detected: tenant was modified externally. Upload blocked.
        </div>
      )}

      <div className="deploy-actions">
        <button onClick={checkDrift} disabled={loading} className="btn btn--secondary btn--sm">Check Drift</button>
        <button onClick={() => setShowApproval(true)} disabled={loading || !state} className="btn btn--primary btn--sm">Approve</button>
      </div>

      {state && <DeploymentStatusCard state={state} />}
      {drift && <DriftReportDialog report={drift} onClose={() => setDrift(null)} />}
      {showApproval && <ApprovalDialog onClose={() => setShowApproval(false)} onApprove={() => { setShowApproval(false); fetchState(); }} />}
    </div>
  );
}
