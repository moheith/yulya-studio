import React, { useState, useRef, useEffect } from 'react';
import { ActivityLog } from '../types';
import { Terminal as TerminalIcon, Trash2 } from 'lucide-react';

interface TerminalProps {
  logs: ActivityLog[];
  height?: number;
  onClearLogs: () => void;
}

export const Terminal: React.FC<TerminalProps> = ({ logs, height, onClearLogs }) => {
  const [filter, setFilter] = useState<'all' | 'ai' | 'build' | 'error'>('all');
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [logs]);

  const filteredLogs = logs.filter((log) => {
    if (filter === 'all') return true;
    if (filter === 'ai') return log.level === 'ai' || log.level === 'tool';
    if (filter === 'build') return log.level === 'info' || log.level === 'success';
    if (filter === 'error') return log.level === 'error' || log.level === 'warning';
    return true;
  });

  const getLevelColor = (level: ActivityLog['level']) => {
    switch (level) {
      case 'success':
        return 'var(--accent-green)';
      case 'warning':
        return 'var(--accent-amber)';
      case 'error':
        return 'var(--accent-rose)';
      case 'ai':
        return 'var(--accent-primary)';
      case 'tool':
        return 'var(--accent-blue)';
      default:
        return 'var(--text-secondary)';
    }
  };

  return (
    <div
      style={{
        height: height !== undefined ? `${height}px` : '140px',
        backgroundColor: 'var(--bg-base)',
        borderTop: '1px solid var(--border-subtle)',
        display: 'flex',
        flexDirection: 'column',
      }}
    >
      {/* Terminal Title Bar */}
      <div
        style={{
          height: '28px',
          padding: '0 12px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          borderBottom: '1px solid var(--border-subtle)',
          backgroundColor: 'var(--bg-elevated)',
          userSelect: 'none',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <TerminalIcon size={12} color="var(--accent-primary)" />
          <span style={{ fontSize: '11px', fontWeight: 700, letterSpacing: '0.5px' }}>
            TERMINAL
          </span>
          <div style={{ display: 'flex', gap: '4px', marginLeft: '12px' }}>
            {(['all', 'ai', 'build', 'error'] as const).map((f) => (
              <button
                key={f}
                onClick={() => setFilter(f)}
                style={{
                  background: filter === f ? 'var(--bg-surface)' : 'transparent',
                  border: 'none',
                  color: filter === f ? 'var(--text-primary)' : 'var(--text-tertiary)',
                  fontSize: '11px',
                  fontWeight: 600,
                  padding: '2px 6px',
                  borderRadius: '3px',
                  cursor: 'pointer',
                  textTransform: 'uppercase',
                }}
              >
                {f}
              </button>
            ))}
          </div>
        </div>

        <button
          onClick={onClearLogs}
          title="Clear Terminal"
          style={{
            background: 'transparent',
            border: 'none',
            color: 'var(--text-tertiary)',
            cursor: 'pointer',
            padding: '2px',
          }}
        >
          <Trash2 size={12} />
        </button>
      </div>

      {/* Terminal Content Feed */}
      <div
        ref={scrollRef}
        style={{
          flex: 1,
          overflowY: 'auto',
          padding: '6px 12px',
          fontFamily: 'var(--font-mono)',
          fontSize: '12px',
          lineHeight: '1.6',
        }}
      >
        {filteredLogs.length === 0 ? (
          <div style={{ color: 'var(--text-tertiary)', fontStyle: 'italic', padding: '8px 0' }}>
            Studio initialized. Ready for commands or voice discussion.
          </div>
        ) : (
          filteredLogs.map((log) => (
            <div key={log.id} style={{ display: 'flex', gap: '10px' }}>
              <span style={{ color: 'var(--text-tertiary)', minWidth: '60px' }}>
                {log.timestamp}
              </span>
              <span
                style={{
                  color: getLevelColor(log.level),
                  fontWeight: 600,
                  minWidth: '55px',
                  textTransform: 'uppercase',
                  fontSize: '11px',
                }}
              >
                [{log.level}]
              </span>
              <span style={{ color: 'var(--text-primary)', wordBreak: 'break-word', flex: 1 }}>
                {log.message}
              </span>
            </div>
          ))
        )}
      </div>
    </div>
  );
};
