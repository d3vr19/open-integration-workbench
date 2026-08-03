/**
 * PalettePanel — draggable step palette (spec §9.4).
 *
 * Extracted from App.tsx as part of OW-029 (full SPA decomposition).
 * Renders the list of available step types with fidelity-colored dots.
 * Users drag palette items onto the FlowCanvas to add nodes.
 */

import { fidelityColor } from '../../flow-utils';

export const PALETTE_STEPS = [
  { type: 'modifier.content', name: 'Content Modifier', fidelity: 'compatible-subset' },
  { type: 'validator.json-schema', name: 'JSON Schema Validator', fidelity: 'compatible-subset' },
  { type: 'script.groovy', name: 'Groovy Script', fidelity: 'simulated' },
  { type: 'transform.xslt', name: 'XSLT Transform', fidelity: 'compatible-subset' },
  { type: 'router.content-based', name: 'Content Router', fidelity: 'compatible-subset' },
  { type: 'filter', name: 'Filter', fidelity: 'compatible-subset' },
  { type: 'converter.json-to-xml', name: 'JSON → XML', fidelity: 'compatible-subset' },
  { type: 'converter.xml-to-json', name: 'XML → JSON', fidelity: 'compatible-subset' },
  { type: 'encoder.base64', name: 'Base64 Encoder', fidelity: 'compatible-subset' },
  { type: 'splitter.general', name: 'Splitter', fidelity: 'simulated' },
  { type: 'gather', name: 'Gather', fidelity: 'simulated' },
  { type: 'receiver.http', name: 'HTTP Receiver', fidelity: 'simulated' },
  { type: 'receiver.sftp', name: 'SFTP Receiver', fidelity: 'simulated' },
  { type: 'log.message', name: 'Log', fidelity: 'compatible-subset' },
];

interface PalettePanelProps {
  onDragStart: (e: React.DragEvent, stepType: string) => void;
  visible: boolean;
}

export function PalettePanel({ onDragStart, visible }: PalettePanelProps) {
  if (!visible) return null;
  return (
    <div className="sidebar__section">
      <h3 className="sidebar__title">Palette</h3>
      <p className="palette__hint">Drag onto canvas</p>
      <div className="palette">
        {PALETTE_STEPS.map((step) => (
          <div
            key={step.type}
            className="palette__item"
            draggable
            onDragStart={(e) => onDragStart(e, step.type)}
          >
            <span
              className="palette__dot"
              style={{ background: fidelityColor(step.fidelity) }}
            />
            <span className="palette__name">{step.name}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
