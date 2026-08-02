/**
 * CoPilotPanel — the LLM-driven co-pilot chat interface.
 *
 * WP-04 Task 9 / spec §12.3 (Interaction Modes): the co-pilot panel
 * lets the user type a natural-language requirement, see the agent's
 * proposed plan, approve it, and watch the changes apply.
 *
 * Flow:
 *  1. User types a requirement in the input box.
 *  2. User clicks "Suggest" → calls api.plan() → shows PlanApprovalDialog.
 *  3. User approves → calls api.implement() → trajectory indicator
 *     turns red (recording) then green (recorded) → shows PatchPreviewDialog.
 *  4. User rejects → dialog closes, no API call.
 *
 * Trajectory recording is implicit (the server records every agent
 * session); the UI just shows the status. The trajectory ID is not
 * currently returned by the REST API, so the indicator shows
 * 'recorded' without an ID. A future API extension can return the
 * trajectory ID for direct linking.
 *
 * Props:
 *  - projectId: the currently selected project
 *  - flowId: the currently selected flow (optional; the agent will
 *    pick the project's only flow if omitted)
 *  - onApplied: callback invoked after a successful implement, so the
 *    parent can re-fetch the flow + validation state
 */

import { useState } from 'react';
import { api } from '../../api';
import type { AgentPlanResponse, AgentImplementResponse } from '../../api';
import { TrajectoryIndicator, type TrajectoryStatus } from './TrajectoryIndicator';
import { PlanApprovalDialog } from './PlanApprovalDialog';
import { PatchPreviewDialog } from './PatchPreviewDialog';

interface CoPilotPanelProps {
  projectId: string | null;
  flowId: string | null;
  onApplied?: () => void;
}

type PanelState =
  | { kind: 'idle' }
  | { kind: 'planning'; requirement: string }
  | { kind: 'plan-ready'; requirement: string; plan: AgentPlanResponse }
  | { kind: 'executing'; plan: AgentPlanResponse }
  | { kind: 'applied'; result: AgentImplementResponse }
  | { kind: 'error'; message: string };

const SUGGESTIONS = [
  'Add JSON schema validation to the flow',
  'Add a default exception subprocess',
  'Increase the receiver timeout to 60 seconds',
  'Add a test for the happy path',
];

export function CoPilotPanel({ projectId, flowId, onApplied }: CoPilotPanelProps) {
  const [input, setInput] = useState('');
  const [state, setState] = useState<PanelState>({ kind: 'idle' });
  const [trajectoryStatus, setTrajectoryStatus] = useState<TrajectoryStatus>('idle');
  const [history, setHistory] = useState<Array<{ requirement: string; success: boolean; timestamp: number }>>([]);

  const disabled = !projectId || state.kind === 'planning' || state.kind === 'executing';

  async function handleSuggest() {
    if (!projectId || !input.trim()) return;
    const requirement = input.trim();
    setState({ kind: 'planning', requirement });
    setTrajectoryStatus('recording');
    try {
      const plan = await api.plan(projectId, requirement, flowId ?? undefined);
      setState({ kind: 'plan-ready', requirement, plan });
      // Trajectory is "recorded" up to this point (the server records
      // every agent session, including plan-only calls).
      setTrajectoryStatus('recorded');
    } catch (e) {
      setState({ kind: 'error', message: String(e) });
      setTrajectoryStatus('failed');
    }
  }

  async function handleApprove() {
    if (state.kind !== 'plan-ready' || !projectId) return;
    const { requirement, plan } = state;
    setState({ kind: 'executing', plan });
    setTrajectoryStatus('recording');
    try {
      const result = await api.implement(projectId, requirement, flowId ?? undefined);
      setState({ kind: 'applied', result });
      setTrajectoryStatus(result.success ? 'recorded' : 'failed');
      setHistory((h) => [...h, { requirement, success: result.success, timestamp: Date.now() }]);
      if (result.success && onApplied) {
        onApplied();
      }
    } catch (e) {
      setState({ kind: 'error', message: String(e) });
      setTrajectoryStatus('failed');
    }
  }

  function handleReject() {
    setState({ kind: 'idle' });
    setTrajectoryStatus('recorded');
    // Keep the input so the user can edit and retry.
  }

  function handleClosePatchPreview() {
    setState({ kind: 'idle' });
    setInput('');
  }

  function handleClearError() {
    setState({ kind: 'idle' });
  }

  function handleSuggestionClick(suggestion: string) {
    setInput(suggestion);
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    // Ctrl/Cmd+Enter submits the requirement.
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
      e.preventDefault();
      handleSuggest();
    }
  }

  return (
    <div className="copilot-panel">
      <div className="copilot-panel__header">
        <h3 className="copilot-panel__title">Co-Pilot</h3>
        <TrajectoryIndicator status={trajectoryStatus} />
      </div>

      {/* Requirement input */}
      <div className="copilot-panel__input-group">
        <textarea
          className="copilot-panel__input"
          placeholder={
            projectId
              ? 'Describe what you want to do… (Ctrl+Enter to submit)'
              : 'Select a project first…'
          }
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={!projectId}
          rows={3}
        />
        <button
          className="btn btn--primary copilot-panel__submit"
          onClick={handleSuggest}
          disabled={disabled || !input.trim()}
        >
          {state.kind === 'planning' ? 'Planning…' : 'Suggest'}
        </button>
      </div>

      {/* Suggestions */}
      {state.kind === 'idle' && history.length === 0 && (
        <div className="copilot-panel__suggestions">
          <p className="copilot-panel__suggestions-label">Try:</p>
          {SUGGESTIONS.map((s) => (
            <button
              key={s}
              className="copilot-panel__suggestion"
              onClick={() => handleSuggestionClick(s)}
              disabled={!projectId}
            >
              {s}
            </button>
          ))}
        </div>
      )}

      {/* Planning spinner */}
      {state.kind === 'planning' && (
        <div className="copilot-panel__status">
          <span className="spinner" /> Generating plan…
        </div>
      )}

      {/* Executing spinner */}
      {state.kind === 'executing' && (
        <div className="copilot-panel__status">
          <span className="spinner" /> Executing plan…
        </div>
      )}

      {/* Error */}
      {state.kind === 'error' && (
        <div className="copilot-panel__error">
          <strong>Error:</strong> {state.message}
          <button className="copilot-panel__error-close" onClick={handleClearError}>×</button>
        </div>
      )}

      {/* History */}
      {history.length > 0 && (
        <div className="copilot-panel__history">
          <p className="copilot-panel__history-label">Recent</p>
          {history.slice(-3).reverse().map((h, i) => (
            <div key={i} className={`copilot-panel__history-item ${h.success ? 'copilot-panel__history-item--ok' : 'copilot-panel__history-item--err'}`}>
              <span className="copilot-panel__history-status">{h.success ? '✓' : '✗'}</span>
              <span className="copilot-panel__history-requirement">{h.requirement}</span>
            </div>
          ))}
        </div>
      )}

      {/* Plan approval dialog */}
      {state.kind === 'plan-ready' && (
        <PlanApprovalDialog
          plan={state.plan}
          onApprove={handleApprove}
          onReject={handleReject}
          loading={false}
        />
      )}

      {/* Patch preview dialog */}
      {state.kind === 'applied' && (
        <PatchPreviewDialog
          implementResult={state.result}
          onClose={handleClosePatchPreview}
        />
      )}
    </div>
  );
}
