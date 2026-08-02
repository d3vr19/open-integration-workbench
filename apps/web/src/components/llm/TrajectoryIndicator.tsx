/**
 * TrajectoryIndicator — shows whether the agent is currently recording
 * a trajectory (red dot, pulsing) or has finished (green dot, static).
 *
 * WP-04 Task 9 / spec §15.2: every agent session produces a trajectory
 * YAML in .oiw/trajectories/. The UI surfaces this with a small status
 * dot so the user knows their interaction is being recorded.
 *
 * Props:
 *  - status: 'idle' | 'recording' | 'recorded' | 'failed'
 *  - trajectoryId: shown as a tooltip when recorded
 */

export type TrajectoryStatus = 'idle' | 'recording' | 'recorded' | 'failed';

interface TrajectoryIndicatorProps {
  status: TrajectoryStatus;
  trajectoryId?: string;
}

export function TrajectoryIndicator({ status, trajectoryId }: TrajectoryIndicatorProps) {
  const label = {
    idle: 'Trajectory: idle',
    recording: 'Trajectory: recording…',
    recorded: `Trajectory: ${trajectoryId ?? 'saved'}`,
    failed: 'Trajectory: failed',
  }[status];

  return (
    <span
      className={`trajectory-indicator trajectory-indicator--${status}`}
      title={label}
      role="status"
      aria-label={label}
    >
      <span className="trajectory-indicator__dot" />
      <span className="trajectory-indicator__label">{label}</span>
    </span>
  );
}
