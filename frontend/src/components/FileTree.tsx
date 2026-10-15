import React, { useState } from 'react';
import {
  FileCode,
  FileText,
  FileJson,
  Image,
  Music,
  Folder,
  Plus,
  Trash2,
  Download,
  ChevronRight,
  ChevronDown,
} from 'lucide-react';

interface FileTreeProps {
  files: Record<string, string>;
  activeFile: string;
  dirtyFiles: Set<string>;
  width?: number;
  onSelectFile: (fileName: string) => void;
  onCreateFile: (fileName: string) => void;
  onDeleteFile: (fileName: string) => void;
  onDownloadZip: () => void;
}

export const FileTree: React.FC<FileTreeProps> = ({
  files,
  activeFile,
  dirtyFiles,
  width,
  onSelectFile,
  onCreateFile,
  onDeleteFile,
  onDownloadZip,
}) => {
  const [creating, setCreating] = useState(false);
  const [newFileName, setNewFileName] = useState('');

  const getFileIcon = (fileName: string) => {
    if (fileName.endsWith('.html')) return <FileCode size={14} color="#f43f5e" />;
    if (fileName.endsWith('.css')) return <FileCode size={14} color="#38bdf8" />;
    if (fileName.endsWith('.js') || fileName.endsWith('.mjs')) return <FileCode size={14} color="#fbbf24" />;
    if (fileName.endsWith('.json')) return <FileJson size={14} color="#34d399" />;
    if (/\.(png|jpe?g|webp|svg|gif)$/i.test(fileName)) return <Image size={14} color="#ec4899" />;
    if (/\.(mp3|wav|ogg)$/i.test(fileName)) return <Music size={14} color="#a855f7" />;
    return <FileText size={14} color="var(--text-secondary)" />;
  };

  const handleCreateSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (newFileName.trim()) {
      onCreateFile(newFileName.trim());
      setNewFileName('');
      setCreating(false);
    }
  };

  const fileKeys = Object.keys(files).sort();

  return (
    <div
      style={{
        width: width !== undefined ? `${width}px` : '220px',
        height: '100%',
        backgroundColor: 'var(--bg-base)',
        borderRight: '1px solid var(--border-subtle)',
        display: 'flex',
        flexDirection: 'column',
        userSelect: 'none',
      }}
    >
      {/* Explorer Header */}
      <div
        style={{
          padding: '10px 12px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          borderBottom: '1px solid var(--border-subtle)',
        }}
      >
        <span
          style={{
            fontSize: '11px',
            fontWeight: 700,
            textTransform: 'uppercase',
            color: 'var(--text-tertiary)',
            letterSpacing: '1px',
          }}
        >
          Explorer
        </span>
        <div style={{ display: 'flex', gap: '4px' }}>
          <button
            onClick={() => setCreating(true)}
            title="New File"
            style={{
              background: 'transparent',
              border: 'none',
              cursor: 'pointer',
              color: 'var(--text-secondary)',
              padding: '2px',
            }}
          >
            <Plus size={14} />
          </button>
          <button
            onClick={onDownloadZip}
            title="Download Project ZIP"
            style={{
              background: 'transparent',
              border: 'none',
              cursor: 'pointer',
              color: 'var(--text-secondary)',
              padding: '2px',
            }}
          >
            <Download size={14} />
          </button>
        </div>
      </div>

      {/* New file input form */}
      {creating && (
        <form onSubmit={handleCreateSubmit} style={{ padding: '6px 8px' }}>
          <input
            autoFocus
            type="text"
            placeholder="filename.js"
            value={newFileName}
            onChange={(e) => setNewFileName(e.target.value)}
            onBlur={() => setCreating(false)}
            style={{
              width: '100%',
              backgroundColor: 'var(--bg-elevated)',
              border: '1px solid var(--accent-primary)',
              borderRadius: '4px',
              color: 'var(--text-primary)',
              fontSize: '12px',
              fontFamily: 'var(--font-mono)',
              padding: '4px 6px',
              outline: 'none',
            }}
          />
        </form>
      )}

      {/* File List */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '6px 0' }}>
        {fileKeys.map((name) => {
          const isActive = name === activeFile;
          const isDirty = dirtyFiles.has(name);
          return (
            <div
              key={name}
              onClick={() => onSelectFile(name)}
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                padding: '6px 12px',
                cursor: 'pointer',
                fontSize: '13px',
                backgroundColor: isActive ? 'var(--bg-elevated)' : 'transparent',
                color: isActive ? 'var(--text-primary)' : 'var(--text-secondary)',
                borderLeft: isActive ? '2px solid var(--accent-primary)' : '2px solid transparent',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', overflow: 'hidden' }}>
                {getFileIcon(name)}
                <span
                  style={{
                    fontFamily: 'var(--font-mono)',
                    fontSize: '12px',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                  }}
                >
                  {name}
                </span>
                {isDirty && (
                  <span
                    style={{
                      width: '6px',
                      height: '6px',
                      borderRadius: '50%',
                      backgroundColor: 'var(--accent-amber)',
                      display: 'inline-block',
                    }}
                  />
                )}
              </div>

              {/* Delete action button for non-primary files */}
              {name !== 'index.html' && (
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    if (confirm(`Delete '${name}'?`)) {
                      onDeleteFile(name);
                    }
                  }}
                  title="Delete file"
                  style={{
                    background: 'transparent',
                    border: 'none',
                    cursor: 'pointer',
                    color: 'var(--text-tertiary)',
                    opacity: 0.6,
                    padding: '2px',
                  }}
                >
                  <Trash2 size={12} />
                </button>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
};
