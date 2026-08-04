/**
 * PropertiesPanel — node properties editor (spec §10).
 *
 * Extracted from App.tsx as part of OW-029 (full SPA decomposition).
 * Shows the selected node's ID (editable), type, fidelity, and config.
 * Includes the inline ConfigEditor for editing key-value pairs.
 */

import type { Node } from 'reactflow';

import { fidelityColor } from '../../flow-utils';

interface PropertiesPanelProps {
  selectedNode: Node;
  onUpdateNodeId: (oldId: string, newId: string) => void;
  onUpdateNodeConfig: (nodeId: string, key: string, value: string) => void;
}

export function PropertiesPanel({
  selectedNode,
  onUpdateNodeId,
  onUpdateNodeConfig,
}: PropertiesPanelProps) {
  const data = selectedNode.data as {
    stepType?: string;
    fidelity?: string;
    config?: Record<string, unknown>;
  };

  return (
    <div className="sidebar__section">
      <h3 className="sidebar__title">Node Properties</h3>
      <div className="properties">
        <div className="properties__row">
          <span className="properties__label">ID</span>
          <input
            className="properties__input"
            value={selectedNode.id}
            onChange={(e) => onUpdateNodeId(selectedNode.id, e.target.value)}
          />
        </div>
        <div className="properties__row">
          <span className="properties__label">Type</span>
          <span className="properties__value">{data.stepType}</span>
        </div>
        <div className="properties__row">
          <span className="properties__label">Fidelity</span>
          <span
            className="properties__value"
            style={{ color: fidelityColor(data.fidelity ?? '') }}
          >
            {data.fidelity}
          </span>
        </div>
        <div className="properties__row properties__row--config">
          <span className="properties__label">Config</span>
          <ConfigEditor
            nodeId={selectedNode.id}
            config={data.config || {}}
            onChange={onUpdateNodeConfig}
          />
        </div>
      </div>
    </div>
  );
}

/** Inline config editor — renders each key as a label + text input. */
function ConfigEditor({
  nodeId,
  config,
  onChange,
}: {
  nodeId: string;
  config: Record<string, unknown>;
  onChange: (nodeId: string, key: string, value: string) => void;
}) {
  const keys = Object.keys(config);
  if (keys.length === 0) {
    return <p className="muted">No config. Add keys via YAML or the API.</p>;
  }
  return (
    <div className="config-editor">
      {keys.map((key) => {
        const value = config[key];
        const strValue = typeof value === 'object' ? JSON.stringify(value) : String(value ?? '');
        return (
          <div key={key} className="config-editor__row">
            <label className="config-editor__label">{key}</label>
            <input
              className="config-editor__input"
              value={strValue}
              onChange={(e) => onChange(nodeId, key, e.target.value)}
            />
          </div>
        );
      })}
    </div>
  );
}
