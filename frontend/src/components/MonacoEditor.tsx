import React, { useEffect, useRef, useState } from 'react';
import { X, Save, GitCommit, Split } from 'lucide-react';

interface MonacoEditorProps {
  openTabs: string[];
  activeFile: string;
  files: Record<string, string>;
  dirtyFiles: Set<string>;
  diffView?: { original: string; modified: string; fileName: string } | null;
  onSelectTab: (fileName: string) => void;
  onCloseTab: (fileName: string) => void;
  onChangeContent: (fileName: string, newContent: string) => void;
  onSaveFile: (fileName: string) => void;
  onCloseDiff?: () => void;
}

export const MonacoEditor: React.FC<MonacoEditorProps> = ({
  openTabs,
  activeFile,
  files,
  dirtyFiles,
  diffView,
  onSelectTab,
  onCloseTab,
  onChangeContent,
  onSaveFile,
  onCloseDiff,
}) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const editorInstanceRef = useRef<any>(null);
  const [monacoLoaded, setMonacoLoaded] = useState(false);

  const getLanguage = (fileName: string) => {
    if (fileName.endsWith('.html')) return 'html';
    if (fileName.endsWith('.css')) return 'css';
    if (fileName.endsWith('.js') || fileName.endsWith('.mjs')) return 'javascript';
    if (fileName.endsWith('.json')) return 'json';
    return 'plaintext';
  };

  // Keyboard shortcut for Ctrl+S / Cmd+S
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 's') {
        e.preventDefault();
        if (activeFile) {
          onSaveFile(activeFile);
        }
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [activeFile, onSaveFile]);

  // Initialize Monaco Editor via require.js AMD loader
  useEffect(() => {
    const win = window as any;
    if (win.require && !monacoLoaded) {
      win.require.config({
        paths: {
          vs: 'https://cdnjs.cloudflare.com/ajax/libs/monaco-editor/0.45.0/min/vs',
        },
      });
      win.require(['vs/editor/editor.main'], () => {
        setMonacoLoaded(true);
      });
    }
  }, [monacoLoaded]);

  // Mount/Update editor instance
  useEffect(() => {
    if (!monacoLoaded || !containerRef.current || diffView) return;

    const win = window as any;
    if (!win.monaco) return;

    if (!editorInstanceRef.current) {
      editorInstanceRef.current = win.monaco.editor.create(containerRef.current, {
        value: files[activeFile] || '',
        language: getLanguage(activeFile),
        theme: 'vs-dark',
        fontFamily: "'JetBrains Mono', monospace",
        fontSize: 13,
        lineNumbers: 'on',
        minimap: { enabled: false },
        scrollBeyondLastLine: false,
        automaticLayout: true,
        tabSize: 2,
        renderLineHighlight: 'all',
      });

      editorInstanceRef.current.onDidChangeModelContent(() => {
        const val = editorInstanceRef.current.getValue();
        onChangeContent(activeFile, val);
      });
    } else {
      const currentVal = editorInstanceRef.current.getValue();
      const targetVal = files[activeFile] || '';
      if (currentVal !== targetVal) {
        editorInstanceRef.current.setValue(targetVal);
      }
      const model = editorInstanceRef.current.getModel();
      if (model) {
        win.monaco.editor.setModelLanguage(model, getLanguage(activeFile));
      }
    }
  }, [monacoLoaded, activeFile, diffView]);

  return (
    <div
      style={{
        flex: 1,
        height: '100%',
        display: 'flex',
        flexDirection: 'column',
        backgroundColor: 'var(--bg-deepest)',
      }}
    >
      {/* Multi-Tab Bar & Save Action */}
      <div
        style={{
          height: '36px',
          backgroundColor: 'var(--bg-base)',
          borderBottom: '1px solid var(--border-subtle)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          paddingRight: '12px',
          overflowX: 'auto',
          userSelect: 'none',
        }}
      >
        <div style={{ display: 'flex', height: '100%', overflowX: 'auto' }}>
          {openTabs.map((tab) => {
            const isActive = tab === activeFile;
            const isDirty = dirtyFiles.has(tab);
            return (
              <div
                key={tab}
                onClick={() => onSelectTab(tab)}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '6px',
                  padding: '0 12px',
                  height: '100%',
                  fontSize: '12px',
                  fontFamily: 'var(--font-mono)',
                  cursor: 'pointer',
                  borderRight: '1px solid var(--border-subtle)',
                  backgroundColor: isActive ? 'var(--bg-deepest)' : 'transparent',
                  color: isActive ? 'var(--text-primary)' : 'var(--text-secondary)',
                  borderTop: isActive ? '2px solid var(--accent-primary)' : '2px solid transparent',
                }}
              >
                <span>{tab}</span>
                {isDirty && (
                  <span
                    style={{
                      width: '6px',
                      height: '6px',
                      borderRadius: '50%',
                      backgroundColor: 'var(--accent-amber)',
                    }}
                  />
                )}
                {openTabs.length > 1 && (
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      onCloseTab(tab);
                    }}
                    style={{
                      background: 'transparent',
                      border: 'none',
                      cursor: 'pointer',
                      color: 'var(--text-tertiary)',
                      display: 'flex',
                      alignItems: 'center',
                      padding: '2px',
                      borderRadius: '2px',
                    }}
                  >
                    <X size={12} />
                  </button>
                )}
              </div>
            );
          })}
        </div>

        {/* Toolbar Actions */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          {diffView && onCloseDiff && (
            <button
              onClick={onCloseDiff}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '4px',
                backgroundColor: 'rgba(56, 189, 248, 0.15)',
                border: '1px solid var(--accent-blue)',
                color: 'var(--accent-blue)',
                padding: '3px 8px',
                borderRadius: '4px',
                fontSize: '11px',
                fontWeight: 600,
                cursor: 'pointer',
              }}
            >
              <Split size={12} />
              <span>Close Diff</span>
            </button>
          )}

          {activeFile && (
            <button
              onClick={() => onSaveFile(activeFile)}
              disabled={!dirtyFiles.has(activeFile)}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '4px',
                backgroundColor: dirtyFiles.has(activeFile)
                  ? 'var(--accent-primary)'
                  : 'transparent',
                border: dirtyFiles.has(activeFile)
                  ? 'none'
                  : '1px solid var(--border-subtle)',
                color: dirtyFiles.has(activeFile) ? '#ffffff' : 'var(--text-tertiary)',
                padding: '4px 10px',
                borderRadius: '4px',
                fontSize: '11px',
                fontWeight: 600,
                cursor: dirtyFiles.has(activeFile) ? 'pointer' : 'default',
              }}
            >
              <Save size={12} />
              <span>Save (Ctrl+S)</span>
            </button>
          )}
        </div>
      </div>

      {/* Editor Body */}
      <div style={{ flex: 1, position: 'relative' }}>
        {diffView ? (
          <div
            style={{
              display: 'flex',
              height: '100%',
              width: '100%',
              backgroundColor: '#0a0a0f',
            }}
          >
            <div
              style={{
                flex: 1,
                borderRight: '1px solid var(--border-subtle)',
                display: 'flex',
                flexDirection: 'column',
              }}
            >
              <div
                style={{
                  padding: '6px 12px',
                  backgroundColor: 'rgba(244, 63, 94, 0.1)',
                  color: 'var(--accent-rose)',
                  fontSize: '12px',
                  fontWeight: 600,
                  fontFamily: 'var(--font-mono)',
                }}
              >
                Original: {diffView.fileName}
              </div>
              <pre
                style={{
                  flex: 1,
                  padding: '12px',
                  overflow: 'auto',
                  fontFamily: 'var(--font-mono)',
                  fontSize: '12px',
                  color: 'var(--text-secondary)',
                }}
              >
                {diffView.original}
              </pre>
            </div>
            <div style={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
              <div
                style={{
                  padding: '6px 12px',
                  backgroundColor: 'rgba(52, 211, 153, 0.1)',
                  color: 'var(--accent-green)',
                  fontSize: '12px',
                  fontWeight: 600,
                  fontFamily: 'var(--font-mono)',
                }}
              >
                Proposed: {diffView.fileName}
              </div>
              <pre
                style={{
                  flex: 1,
                  padding: '12px',
                  overflow: 'auto',
                  fontFamily: 'var(--font-mono)',
                  fontSize: '12px',
                  color: 'var(--text-primary)',
                }}
              >
                {diffView.modified}
              </pre>
            </div>
          </div>
        ) : monacoLoaded ? (
          <div ref={containerRef} style={{ width: '100%', height: '100%' }} />
        ) : (
          <textarea
            value={files[activeFile] || ''}
            onChange={(e) => onChangeContent(activeFile, e.target.value)}
            style={{
              width: '100%',
              height: '100%',
              backgroundColor: 'var(--bg-deepest)',
              color: 'var(--text-primary)',
              fontFamily: 'var(--font-mono)',
              fontSize: '13px',
              padding: '16px',
              border: 'none',
              outline: 'none',
              resize: 'none',
              lineHeight: '1.6',
            }}
          />
        )}
      </div>
    </div>
  );
};
