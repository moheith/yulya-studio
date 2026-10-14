import React from 'react';
import { ToastItem } from '../types';
import { CheckCircle2, AlertCircle, Info, AlertTriangle, X } from 'lucide-react';

interface ToastContainerProps {
  toasts: ToastItem[];
  onDismiss: (id: string) => void;
}

export const ToastContainer: React.FC<ToastContainerProps> = ({ toasts, onDismiss }) => {
  if (toasts.length === 0) return null;

  const getIcon = (type: ToastItem['type']) => {
    switch (type) {
      case 'success':
        return <CheckCircle2 size={16} color="var(--accent-green)" />;
      case 'error':
        return <AlertCircle size={16} color="var(--accent-rose)" />;
      case 'warning':
        return <AlertTriangle size={16} color="var(--accent-amber)" />;
      default:
        return <Info size={16} color="var(--accent-blue)" />;
    }
  };

  const getBorderColor = (type: ToastItem['type']) => {
    switch (type) {
      case 'success':
        return 'var(--accent-green)';
      case 'error':
        return 'var(--accent-rose)';
      case 'warning':
        return 'var(--accent-amber)';
      default:
        return 'var(--accent-blue)';
    }
  };

  return (
    <div
      style={{
        position: 'fixed',
        bottom: '24px',
        right: '24px',
        display: 'flex',
        flexDirection: 'column',
        gap: '8px',
        zIndex: 300,
        maxWidth: '380px',
      }}
    >
      {toasts.map((t) => (
        <div
          key={t.id}
          style={{
            backgroundColor: 'var(--bg-elevated)',
            borderLeft: `4px solid ${getBorderColor(t.type)}`,
            borderTop: '1px solid var(--border-subtle)',
            borderRight: '1px solid var(--border-subtle)',
            borderBottom: '1px solid var(--border-subtle)',
            borderRadius: '6px',
            padding: '10px 14px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: '10px',
            boxShadow: '0 6px 20px rgba(0,0,0,0.5)',
            fontSize: '13px',
            color: 'var(--text-primary)',
            animation: 'fadeIn 0.2s ease',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flex: 1 }}>
            {getIcon(t.type)}
            <span>{t.message}</span>
          </div>
          <button
            onClick={() => onDismiss(t.id)}
            style={{
              background: 'transparent',
              border: 'none',
              color: 'var(--text-tertiary)',
              cursor: 'pointer',
              padding: '2px',
            }}
          >
            <X size={13} />
          </button>
        </div>
      ))}
    </div>
  );
};
