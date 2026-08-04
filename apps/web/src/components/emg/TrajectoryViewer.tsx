/** TrajectoryViewer — expandable trajectory details. WP-06 E-003. */

interface TrajectoryViewerProps {
  insightId: string;
}

export function TrajectoryViewer({ insightId }: TrajectoryViewerProps) {
  return (
    <div className="trajectory-viewer" data-insight-id={insightId}>
      <details>
        <summary className="trajectory-viewer__summary">View trajectory details</summary>
        <div className="trajectory-viewer__body">
          <p className="muted">Loading trajectory for {insightId}…</p>
        </div>
      </details>
    </div>
  );
}
