/** DriftReportDialog — drift detection results. WP-06 E-002. */

interface DriftReport {
  status: string;
  safeToUpload: boolean;
  localDigest?: string;
  tenantDigest?: string;
  recommendation?: string;
}

export function DriftReportDialog({ report, onClose }: { report: DriftReport; onClose: () => void }) {
  const isError = report.status === 'DRIFT_DETECTED';
  return (
    <div className="dialog-backdrop" role="dialog" aria-modal="true">
      <div className="dialog dialog--drift">
        <div className="dialog__header">
          <h2 className="dialog__title">Drift Detection</h2>
          <button className="dialog__close" onClick={onClose}>×</button>
        </div>
        <div className="dialog__body">
          <div className={`drift-status ${isError ? 'drift-status--err' : 'drift-status--ok'}`}>
            <span className="drift-status__label">{report.status}</span>
            <span className="drift-status__safe">{report.safeToUpload ? '✓ Safe to upload' : '✗ Upload blocked'}</span>
          </div>
          {report.localDigest && (
            <div className="drift-detail"><span>Local:</span> <code>{report.localDigest}</code></div>
          )}
          {report.tenantDigest && (
            <div className="drift-detail"><span>Tenant:</span> <code>{report.tenantDigest}</code></div>
          )}
          {report.recommendation && (
            <div className="drift-recommendation">{report.recommendation}</div>
          )}
        </div>
        <div className="dialog__footer">
          <button className="btn btn--primary" onClick={onClose}>Close</button>
        </div>
      </div>
    </div>
  );
}
