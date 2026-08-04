/** ApprovalDialog — approve/reject deployment. WP-06 E-002. */
import { useState } from 'react';

export function ApprovalDialog({ onClose, onApprove }: { onClose: () => void; onApprove: (approver: string) => void }) {
  const [approver, setApprover] = useState('');
  const [error, setError] = useState('');

  const handleApprove = () => {
    if (!approver.trim()) {
      setError('Approver name is required');
      return;
    }
    onApprove(approver.trim());
  };

  return (
    <div className="dialog-backdrop" role="dialog" aria-modal="true">
      <div className="dialog dialog--approval">
        <div className="dialog__header">
          <h2 className="dialog__title">Approve Deployment</h2>
          <button className="dialog__close" onClick={onClose}>×</button>
        </div>
        <div className="dialog__body">
          <p>Enter your name to approve this deployment. This will be recorded in the deployment history.</p>
          <input
            className="properties__input"
            placeholder="Approver name (required)"
            value={approver}
            onChange={e => { setApprover(e.target.value); setError(''); }}
            autoFocus
          />
          {error && <div className="deploy-error">{error}</div>}
        </div>
        <div className="dialog__footer">
          <button className="btn btn--secondary" onClick={onClose}>Cancel</button>
          <button className="btn btn--primary" onClick={handleApprove} disabled={!approver.trim()}>Approve</button>
        </div>
      </div>
    </div>
  );
}
