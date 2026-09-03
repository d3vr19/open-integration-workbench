import { useMemo, useState, useEffect, useCallback } from 'react';
import type { SimulationResult, TraceEntry } from '../../api';

/**
 * TraceInspector — FIGAF-style interactive trace viewer (v1.5).
 *
 * WP-09 Track B (B-001 & B-002):
 * - Canvas node badges wired to inspector via selectedNodeId / onSelectNodeId
 * - Replay / step-through transport mode (step forward, back, play/pause)
 */

interface NodeStep {
  nodeId: string;
  enter?: TraceEntry;
  exit?: TraceEntry;
  error?: TraceEntry;
  durationMs: number | null;
  outbound?: { method: string; url: string; body?: string; requestHeaders?: Record<string, unknown> };
}

function buildSteps(sim: SimulationResult): NodeStep[] {
  const steps = new Map<string, NodeStep>();
  for (const t of sim.trace) {
    const step =
      steps.get(t.node_id) ?? { nodeId: t.node_id, durationMs: null };
    if (t.direction === 'enter') step.enter = t;
    else if (t.direction === 'exit') {
      step.exit = t;
      if (t.duration_ms != null) step.durationMs = t.duration_ms;
    } else if (t.direction === 'error') {
      step.error = t;
      if (t.duration_ms != null) step.durationMs = t.duration_ms;
    }
    steps.set(t.node_id, step);
  }
  for (const c of sim.outbound_calls) {
    const step = steps.get(c.target);
    if (step) {
      step.outbound = {
        method: c.method,
        url: c.url,
        body: c.body,
        requestHeaders: c.requestHeaders,
      };
    }
  }
  return [...steps.values()];
}

function JsonBlock({ label, value }: { label: string; value: unknown }) {
  if (value == null) return null;
  const text =
    typeof value === 'string'
      ? value
      : JSON.stringify(value, null, 2);
  if (!text || text === '{}' || text === 'null') return null;
  return (
    <div className="trace-inspector__block">
      <div className="trace-inspector__block-label">{label}</div>
      <pre className="trace-inspector__pre">{text}</pre>
    </div>
  );
}

function PropsTable({ props }: { props: Record<string, unknown> | null }) {
  const entries = Object.entries(props ?? {}).filter(
    ([, v]) => v !== '' && v != null,
  );
  if (entries.length === 0) return null;
  return (
    <div className="trace-inspector__block">
      <div className="trace-inspector__block-label">Properties</div>
      <table className="trace-inspector__props">
        <tbody>
          {entries.map(([k, v]) => (
            <tr key={k}>
              <td className="trace-inspector__prop-key">{k}</td>
              <td className="trace-inspector__prop-val">{String(v)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

interface TraceInspectorProps {
  simulation: SimulationResult;
  selectedNodeId?: string | null;
  onSelectNodeId?: (nodeId: string | null) => void;
}

export function TraceInspector({ simulation, selectedNodeId, onSelectNodeId }: TraceInspectorProps) {
  const steps = useMemo(() => buildSteps(simulation), [simulation]);
  const [selectedIdx, setSelectedIdx] = useState<number | null>(null);
  const [isPlaying, setIsPlaying] = useState(false);

  // Sync with external selectedNodeId (B-001: canvas badge click -> inspector step)
  useEffect(() => {
    if (selectedNodeId) {
      const idx = steps.findIndex((s) => s.nodeId === selectedNodeId);
      if (idx !== -1 && idx !== selectedIdx) {
        setSelectedIdx(idx);
      }
    }
  }, [selectedNodeId, steps, selectedIdx]);

  // Notify parent on step change
  const selectStep = useCallback(
    (idx: number | null) => {
      setSelectedIdx(idx);
      if (idx != null && steps[idx]) {
        onSelectNodeId?.(steps[idx].nodeId);
      } else {
        onSelectNodeId?.(null);
      }
    },
    [steps, onSelectNodeId],
  );

  // B-002: Transport step-through controls
  const handleFirst = useCallback(() => {
    setIsPlaying(false);
    if (steps.length > 0) selectStep(0);
  }, [steps.length, selectStep]);

  const handlePrev = useCallback(() => {
    setIsPlaying(false);
    if (steps.length === 0) return;
    const nextIdx = selectedIdx == null ? steps.length - 1 : Math.max(0, selectedIdx - 1);
    selectStep(nextIdx);
  }, [selectedIdx, steps.length, selectStep]);

  const handleNext = useCallback(() => {
    setIsPlaying(false);
    if (steps.length === 0) return;
    const nextIdx = selectedIdx == null ? 0 : Math.min(steps.length - 1, selectedIdx + 1);
    selectStep(nextIdx);
  }, [selectedIdx, steps.length, selectStep]);

  const handleLast = useCallback(() => {
    setIsPlaying(false);
    if (steps.length > 0) selectStep(steps.length - 1);
  }, [steps.length, selectStep]);

  const togglePlay = useCallback(() => {
    setIsPlaying((playing) => !playing);
  }, []);

  // Autoplay timer
  useEffect(() => {
    if (!isPlaying || steps.length === 0) return;
    const interval = setInterval(() => {
      setSelectedIdx((prev) => {
        const next = prev == null ? 0 : prev + 1;
        if (next >= steps.length) {
          setIsPlaying(false);
          return prev;
        }
        onSelectNodeId?.(steps[next].nodeId);
        return next;
      });
    }, 1200);
    return () => clearInterval(interval);
  }, [isPlaying, steps, onSelectNodeId]);

  if (steps.length === 0) {
    return <div className="trace-inspector__empty">No trace entries.</div>;
  }

  const selected = selectedIdx != null ? steps[selectedIdx] : null;

  return (
    <div className="trace-inspector" data-testid="trace-inspector">
      {/* B-002: Replay transport control bar */}
      <div className="trace-inspector__transport" data-testid="trace-transport">
        <button
          className="trace-inspector__transport-btn"
          onClick={handleFirst}
          disabled={selectedIdx === 0}
          title="Jump to first step"
        >
          ⏮
        </button>
        <button
          className="trace-inspector__transport-btn"
          onClick={handlePrev}
          disabled={selectedIdx === 0}
          title="Previous step"
        >
          ◀
        </button>
        <button
          className={`trace-inspector__transport-btn ${isPlaying ? 'trace-inspector__transport-btn--active' : ''}`}
          onClick={togglePlay}
          title={isPlaying ? 'Pause replay' : 'Play replay'}
        >
          {isPlaying ? '⏸' : '▶'}
        </button>
        <button
          className="trace-inspector__transport-btn"
          onClick={handleNext}
          disabled={selectedIdx === steps.length - 1}
          title="Next step"
        >
          ▶
        </button>
        <button
          className="trace-inspector__transport-btn"
          onClick={handleLast}
          disabled={selectedIdx === steps.length - 1}
          title="Jump to last step"
        >
          ⏭
        </button>
        <span className="trace-inspector__transport-counter">
          {selectedIdx != null ? `Step ${selectedIdx + 1} of ${steps.length}` : `${steps.length} steps`}
        </span>
      </div>

      <div className="trace-inspector__steps">
        {steps.map((s, i) => (
          <button
            key={s.nodeId}
            className={`trace-inspector__step
              ${s.error ? 'trace-inspector__step--error' : ''}
              ${selectedIdx === i ? 'trace-inspector__step--active' : ''}`}
            onClick={() => selectStep(i === selectedIdx ? null : i)}
            title={s.error ? `${s.error.exception_type ?? 'error'}: ${s.error.summary}` : s.nodeId}
            data-testid={`trace-step-${s.nodeId}`}
          >
            <span className="trace-inspector__step-name">{s.nodeId}</span>
            <span className="trace-inspector__step-status">
              {s.error ? '✖' : '✓'}
            </span>
            {s.durationMs != null && (
              <span className="trace-inspector__step-ms">{s.durationMs}ms</span>
            )}
          </button>
        ))}
      </div>

      {selected && (
        <div className="trace-inspector__detail" data-testid="trace-detail">
          <div className="trace-inspector__detail-header">
            <span className="trace-inspector__node-id">{selected.nodeId}</span>
            {selected.error && (
              <span className="trace-inspector__error-type">
                {selected.error.exception_type ?? 'Error'}
              </span>
            )}
          </div>

          {selected.error && (
            <JsonBlock label="Error summary" value={selected.error.summary} />
          )}

          <div className="trace-inspector__io">
            <div className="trace-inspector__io-col">
              <div className="trace-inspector__io-title">In</div>
              <JsonBlock label="Body" value={selected.enter?.body_preview} />
              <JsonBlock label="Headers" value={selected.enter?.headers} />
              <PropsTable props={selected.enter?.properties ?? null} />
            </div>
            <div className="trace-inspector__io-col">
              <div className="trace-inspector__io-title">Out</div>
              <JsonBlock label="Body" value={(selected.exit ?? selected.error)?.body_preview} />
              <JsonBlock label="Headers" value={(selected.exit ?? selected.error)?.headers} />
              <PropsTable props={(selected.exit ?? selected.error)?.properties ?? null} />
            </div>
          </div>

          {selected.outbound && (
            <div className="trace-inspector__block">
              <div className="trace-inspector__block-label">
                Outbound call
              </div>
              <div className="trace-inspector__outbound">
                <span className="trace-inspector__outbound-method">
                  {selected.outbound.method}
                </span>{' '}
                <span className="trace-inspector__outbound-url">
                  {selected.outbound.url}
                </span>
              </div>
              <JsonBlock label="Request body" value={selected.outbound.body} />
              <JsonBlock label="Request headers" value={selected.outbound.requestHeaders} />
            </div>
          )}
        </div>
      )}
    </div>
  );
}
