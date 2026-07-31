/**
 * Monaco-based resource editor.
 * Spec ref: §6.1 (Monaco Editor for Groovy, XML, XSLT, JSON, YAML, properties),
 *           §10.3 (editors/ component architecture).
 */

import { useEffect, useState } from 'react';
import Editor from '@monaco-editor/react';
import { api } from './api';
import type { ResourceSummary, ResourceContent } from './api';

interface ResourceEditorProps {
  projectId: string;
  resource: ResourceSummary;
  onClose: () => void;
}

export function ResourceEditor({ projectId, resource, onClose }: ResourceEditorProps) {
  const [content, setContent] = useState<string>('');
  const [originalContent, setOriginalContent] = useState<string>('');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    api.getResource(projectId, resource.path).then((res: ResourceContent) => {
      setContent(res.content);
      setOriginalContent(res.content);
    }).catch((e) => setError(String(e))).finally(() => setLoading(false));
  }, [projectId, resource.path]);

  const dirty = content !== originalContent;

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      const res = await api.writeResource(projectId, resource.path, content);
      setOriginalContent(res.content);
      setContent(res.content);
    } catch (e) {
      setError(String(e));
    } finally {
      setSaving(false);
    }
  };

  const handleEditorChange = (value: string | undefined) => {
    setContent(value ?? '');
  };

  return (
    <div className="resource-editor">
      <div className="resource-editor__header">
        <div className="resource-editor__title">
          <span className="resource-editor__name">{resource.name}</span>
          <span className="resource-editor__path">{resource.path}</span>
          <span className="badge badge--mono">{resource.language}</span>
          {dirty && <span className="badge badge--warn">unsaved</span>}
        </div>
        <div className="resource-editor__actions">
          <button
            onClick={save}
            disabled={!dirty || saving}
            className="btn btn--primary btn--sm"
          >
            {saving ? 'Saving…' : 'Save'}
          </button>
          <button onClick={onClose} className="btn btn--secondary btn--sm">
            Close
          </button>
        </div>
      </div>
      {error && <div className="error-banner error-banner--inline">{error}</div>}
      {loading ? (
        <div className="resource-editor__loading">Loading…</div>
      ) : (
        <Editor
          height="100%"
          language={resource.language}
          value={content}
          onChange={handleEditorChange}
          theme="vs-dark"
          options={{
            minimap: { enabled: false },
            fontSize: 13,
            wordWrap: 'on',
            scrollBeyondLastLine: false,
            automaticLayout: true,
            tabSize: 2,
          }}
        />
      )}
    </div>
  );
}
