import { useMemo, useState } from 'react';
import type { SimulationResult, TraceEntry } from '../../api';

/**
 * TraceInspector — FIGAF-style interactive trace viewer.
 *
 * The engine records enter/exit/error snapshots per step (body, headers,
 * properties, durations). This component steps through the exchange the
 * way message-monitoring tools do: pick a step, see the message AS IT WAS
 * entering and leaving that step, the outbound call it produced, and the
 * error details if it failed.
 *
 * Future work (tracked in good-first-issues): overlaying these results
 * onto the canvas nodes + tenant-MPL comparison views.
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

export function TraceInspector({ simulation }: { simulation: SimulationResult }) {
  const steps = useMemo(() => buildSteps(simulation), [simulation]);
  const [selectedIdx, setSelectedIdx] = useState<number | null>(null);
  const selected = selectedIdx != null ? steps[selectedIdx] : null;

  if (steps.length === 0) {
    return <div className="trace-inspector__empty">No trace entries.</div>;
  }

  return (
    <div className="trace-inspector">
      <div className="trace-inspector__steps">
        {steps.map((s, i) => (
          <button
            key={s.nodeId}
            className={`trace-inspector__step
              ${s.error ? 'trace-inspector__step--error' : ''}
              ${selectedIdx === i ? 'trace-inspector__step--active' : ''}`}
            onClick={() => setSelectedIdx(i === selectedIdx ? null : i)}
            title={s.error ? `${s.error.exception_type ?? 'error'}: ${s.error.summary}` : s.nodeId}
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
        <div className="trace-inspector__detail">
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
