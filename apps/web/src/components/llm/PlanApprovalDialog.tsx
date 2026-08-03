/**
 * PlanApprovalDialog — shows the agent's proposed plan as a numbered
 * list with rationale, and lets the user approve or reject.
 *
 * WP-04 Task 9 / spec §12.2 (co-pilot mode): the agent presents the
 * plan before executing. The user reviews assumptions, risks, and
 * step rationales, then approves or rejects.
 *
 * Props:
 *  - plan: the AgentPlanResponse from POST /agents:plan
 *  - onApprove: called when the user clicks Approve
 *  - onReject: called when the user clicks Reject (or closes the dialog)
 */

import type { AgentPlanResponse, PlanStep } from '../../api';

interface PlanApprovalDialogProps {
  plan: AgentPlanResponse;
  onApprove: () => void;
  onReject: () => void;
  loading?: boolean;
}

const TOOL_LABELS: Record<string, string> = {
  'flow.patch': 'Patch flow',
  'resource.write': 'Write resource',
  'test.create': 'Create test',
  'flow.validate': 'Validate',
  'test.run': 'Run tests',
};

function stepLabel(step: PlanStep): string {
  return TOOL_LABELS[step.tool] ?? step.tool;
}

function stepArgumentSummary(step: PlanStep): string {
  // Show a short, human-readable summary of the step's arguments.
  const args = step.arguments;
  if (step.tool === 'flow.patch') {
    const ops = (args.operations as Array<{ op: string; node?: { id?: string; type?: string } }>) ?? [];
    if (ops.length === 0) return '(no operations)';
    if (ops.length === 1) {
      const op = ops[0];
      const node = op.node;
      if (node) return `${op.op} ${node.id ?? ''} (${node.type ?? 'unknown'})`;
      return `${op.op}`;
    }
    return `${ops.length} operations`;
  }
  if (step.tool === 'resource.write') {
    return (args.path as string) ?? '(no path)';
  }
  if (step.tool === 'test.create') {
    return (args.testName as string) ?? '(no name)';
  }
  return JSON.stringify(args).slice(0, 80);
}

export function PlanApprovalDialog({ plan, onApprove, onReject, loading }: PlanApprovalDialogProps) {
  return (
    <div className="dialog-backdrop" role="dialog" aria-modal="true" aria-labelledby="plan-dialog-title">
      <div className="dialog dialog--plan-approval">
        <div className="dialog__header">
          <h2 id="plan-dialog-title" className="dialog__title">Proposed Plan</h2>
          <button
            className="dialog__close"
            onClick={onReject}
            aria-label="Close"
            disabled={loading}
          >
            ×
          </button>
        </div>

        <div className="dialog__body">
          {/* Requirement summary */}
          <section className="plan-section">
            <h3 className="plan-section__title">Requirement</h3>
            <div className="plan-requirement">
              <div className="plan-requirement__row">
                <span className="plan-requirement__label">Intent:</span>
                <span className="badge badge--mono">{plan.requirement.intent}</span>
              </div>
              {plan.requirement.archetype && (
                <div className="plan-requirement__row">
                  <span className="plan-requirement__label">Archetype:</span>
                  <span>{plan.requirement.archetype}</span>
                </div>
              )}
              {plan.requirement.operations.length > 0 && (
                <div className="plan-requirement__row">
                  <span className="plan-requirement__label">Operations:</span>
                  <span>{plan.requirement.operations.join(', ')}</span>
                </div>
              )}
              <div className="plan-requirement__row">
                <span className="plan-requirement__label">Raw:</span>
                <span className="plan-requirement__raw">{plan.requirement.raw}</span>
              </div>
            </div>
          </section>

          {/* Steps */}
          <section className="plan-section">
            <h3 className="plan-section__title">Steps ({plan.steps.length})</h3>
            {plan.steps.length === 0 ? (
              <p className="muted">No steps generated. The agent could not produce a plan for this requirement.</p>
            ) : (
              <ol className="plan-steps">
                {plan.steps.map((step, i) => (
                  <li key={i} className="plan-step">
                    <div className="plan-step__header">
                      <span className="plan-step__index">{step.index}</span>
                      <span className="badge badge--mono">{stepLabel(step)}</span>
                      <span className="plan-step__description">{step.description}</span>
                    </div>
                    <div className="plan-step__args">{stepArgumentSummary(step)}</div>
                  </li>
                ))}
              </ol>
            )}
          </section>

          {/* Assumptions */}
          {plan.assumptions.length > 0 && (
            <section className="plan-section">
              <h3 className="plan-section__title">Assumptions</h3>
              <ul className="plan-assumptions">
                {plan.assumptions.map((a, i) => (
                  <li key={i} className="plan-assumption">{a}</li>
                ))}
              </ul>
            </section>
          )}

          {/* Risks */}
          {plan.risks.length > 0 && (
            <section className="plan-section">
              <h3 className="plan-section__title">Risks</h3>
              <ul className="plan-risks">
                {plan.risks.map((r, i) => (
                  <li key={i} className="plan-risk">{r}</li>
                ))}
              </ul>
            </section>
          )}
        </div>

        <div className="dialog__footer">
          <button
            className="btn btn--secondary"
            onClick={onReject}
            disabled={loading}
          >
            Reject
          </button>
          <button
            className="btn btn--primary"
            onClick={onApprove}
            disabled={loading || plan.steps.length === 0}
          >
            {loading ? 'Executing…' : 'Approve & Execute'}
          </button>
        </div>
      </div>
    </div>
  );
}
