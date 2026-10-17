import React, { useState } from 'react';
import { ModelEntry, User } from '../types';
import { Key, Eye, EyeOff, ShieldCheck, Check, Loader2, Sparkles } from 'lucide-react';
import { saveApiKey } from '../services/api';

interface SettingsModalProps {
  currentUser: User | null;
  liveModels: ModelEntry[];
  codeModels: ModelEntry[];
  selectedLiveModel: string;
  selectedCodeModel: string;
  onSelectLiveModel: (modelId: string) => void;
  onSelectCodeModel: (modelId: string) => void;
  onClose: () => void;
  onShowToast: (msg: string, type?: 'info' | 'success' | 'warning' | 'error') => void;
}

export const SettingsModal: React.FC<SettingsModalProps> = ({
  currentUser,
  liveModels,
  codeModels,
  selectedLiveModel,
  selectedCodeModel,
  onSelectLiveModel,
  onSelectCodeModel,
  onClose,
  onShowToast,
}) => {
  const [apiKey, setApiKey] = useState('');
  const [showKey, setShowKey] = useState(false);
  const [savingKey, setSavingKey] = useState(false);
  const [acceptedTerms, setAcceptedTerms] = useState(true);

  React.useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [onClose]);

  const handleSaveApiKey = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!apiKey.trim()) return;

    if (!acceptedTerms) {
      onShowToast('Please accept the studio terms of service.', 'warning');
      return;
    }

    setSavingKey(true);
    try {
      const res = await saveApiKey(apiKey.trim());
      if (res.success) {
        onShowToast('Google AI Studio API key verified and encrypted at rest!', 'success');
        setApiKey('');
      } else {
        onShowToast(res.message || 'Verification failed', 'error');
      }
    } catch (err: any) {
      onShowToast(err.message || 'Failed to save API key', 'error');
    } finally {
      setSavingKey(false);
    }
  };

  return (
    <div
      style={{
        position: 'fixed',
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        backgroundColor: 'rgba(5, 1, 16, 0.85)',
        backdropFilter: 'blur(8px)',
        display: 'flex',
        justifyContent: 'center',
        alignItems: 'center',
        zIndex: 200,
        padding: '20px',
      }}
      onClick={onClose}
    >
      <div
        style={{
          width: '500px',
          backgroundColor: 'var(--bg-elevated)',
          border: '1px solid var(--border-active)',
          borderRadius: '14px',
          padding: '28px',
          display: 'flex',
          flexDirection: 'column',
          gap: '20px',
          boxShadow: '0 12px 36px rgba(0,0,0,0.7)',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <Key size={18} color="var(--accent-primary)" />
            <h2 style={{ fontSize: '18px', fontWeight: 700 }}>Studio Settings</h2>
          </div>
          <button
            id="close-settings-modal"
            onClick={onClose}
            title="Close Settings"
            style={{
              background: 'transparent',
              border: 'none',
              color: 'var(--text-tertiary)',
              cursor: 'pointer',
              fontSize: '18px',
            }}
          >
            ✕
          </button>
        </div>

        {/* Connect Gemini API Key Form */}
        <form onSubmit={handleSaveApiKey} style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
          <div>
            <label style={{ fontSize: '13px', fontWeight: 600, color: 'var(--text-primary)' }}>
              Google AI Studio API Key
            </label>
            <p style={{ fontSize: '12px', color: 'var(--text-secondary)', marginTop: '2px' }}>
              Used for your private Gemini Live voice session and Antigravity code synthesis. Encrypted at rest.
            </p>
          </div>

          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              backgroundColor: 'var(--bg-deepest)',
              border: '1px solid var(--border-subtle)',
              borderRadius: '8px',
              padding: '0 10px',
            }}
          >
            <input
              type={showKey ? 'text' : 'password'}
              placeholder="AIzaSy..."
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              style={{
                flex: 1,
                background: 'transparent',
                border: 'none',
                color: 'var(--text-primary)',
                fontFamily: 'var(--font-mono)',
                fontSize: '13px',
                padding: '10px 4px',
                outline: 'none',
              }}
            />
            <button
              type="button"
              onClick={() => setShowKey(!showKey)}
              style={{
                background: 'transparent',
                border: 'none',
                color: 'var(--text-tertiary)',
                cursor: 'pointer',
                padding: '4px',
              }}
            >
              {showKey ? <EyeOff size={16} /> : <Eye size={16} />}
            </button>
          </div>

          <label
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
              fontSize: '12px',
              color: 'var(--text-secondary)',
              cursor: 'pointer',
            }}
          >
            <input
              type="checkbox"
              checked={acceptedTerms}
              onChange={(e) => setAcceptedTerms(e.target.checked)}
            />
            <span>I accept the Yulya Studio AI Terms of Service and Guidelines</span>
          </label>

          <button
            type="submit"
            disabled={savingKey || !apiKey.trim()}
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: '6px',
              backgroundColor: 'var(--accent-primary)',
              color: '#ffffff',
              border: 'none',
              borderRadius: '8px',
              padding: '10px',
              fontWeight: 600,
              fontSize: '13px',
              cursor: savingKey || !apiKey.trim() ? 'default' : 'pointer',
              opacity: savingKey || !apiKey.trim() ? 0.6 : 1,
            }}
          >
            {savingKey ? <Loader2 size={16} style={{ animation: 'spin 1s linear infinite' }} /> : <ShieldCheck size={16} />}
            <span>{savingKey ? 'Verifying with Google AI Studio...' : 'Verify & Save Key'}</span>
          </button>
        </form>

        {/* Model Preferences */}
        <div style={{ borderTop: '1px solid var(--border-subtle)', paddingTop: '16px', display: 'flex', flexDirection: 'column', gap: '12px' }}>
          <div>
            <label style={{ fontSize: '13px', fontWeight: 600, color: 'var(--text-primary)' }}>
              Preferred Voice Model
            </label>
            <select
              value={selectedLiveModel}
              onChange={(e) => onSelectLiveModel(e.target.value)}
              style={{
                width: '100%',
                marginTop: '6px',
                backgroundColor: 'var(--bg-deepest)',
                border: '1px solid var(--border-subtle)',
                borderRadius: '6px',
                color: 'var(--text-primary)',
                padding: '8px 12px',
                fontSize: '13px',
                fontFamily: 'var(--font-mono)',
                outline: 'none',
              }}
            >
              {liveModels.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.display_name} {m.recommended ? '(Recommended)' : ''}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label style={{ fontSize: '13px', fontWeight: 600, color: 'var(--text-primary)' }}>
              Preferred Coding Engine Model
            </label>
            <select
              value={selectedCodeModel}
              onChange={(e) => onSelectCodeModel(e.target.value)}
              style={{
                width: '100%',
                marginTop: '6px',
                backgroundColor: 'var(--bg-deepest)',
                border: '1px solid var(--border-subtle)',
                borderRadius: '6px',
                color: 'var(--text-primary)',
                padding: '8px 12px',
                fontSize: '13px',
                fontFamily: 'var(--font-mono)',
                outline: 'none',
              }}
            >
              {codeModels.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.display_name} {m.recommended ? '(Recommended)' : ''}
                </option>
              ))}
            </select>
          </div>
        </div>

        {/* Discord Login Info */}
        <div style={{ borderTop: '1px solid var(--border-subtle)', paddingTop: '14px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <span style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>
            Signed in as: <strong style={{ color: 'var(--text-primary)' }}>@{currentUser?.username || 'Guest'}</strong>
          </span>
          <a
            href="/auth/login"
            style={{
              fontSize: '12px',
              color: 'var(--accent-primary)',
              textDecoration: 'none',
              fontWeight: 600,
            }}
          >
            Re-authenticate via Discord
          </a>
        </div>
      </div>
    </div>
  );
};
