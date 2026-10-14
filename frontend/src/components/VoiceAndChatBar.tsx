import React, { useState, useEffect } from 'react';
import {
  Send,
  Mic,
  MicOff,
  Sparkles,
  Loader2,
  Cpu,
  Volume2,
} from 'lucide-react';
import { LiveSessionState, BuildStage, ModelEntry } from '../types';

interface VoiceAndChatBarProps {
  liveState: LiveSessionState;
  isMuted: boolean;
  userTranscript: string;
  aiTranscript: string;
  buildStage: BuildStage | null;
  buildMessage: string | null;
  codeModels: ModelEntry[];
  selectedCodeModel: string;
  onToggleMute: () => void;
  onSendCommand: (prompt: string, modelId?: string) => void;
  onSelectCodeModel: (modelId: string) => void;
}

export const VoiceAndChatBar: React.FC<VoiceAndChatBarProps> = ({
  liveState,
  isMuted,
  userTranscript,
  aiTranscript,
  buildStage,
  buildMessage,
  codeModels,
  selectedCodeModel,
  onToggleMute,
  onSendCommand,
  onSelectCodeModel,
}) => {
  const [prompt, setPrompt] = useState('');

  // Handle Spacebar hotkey to toggle Mute when not typing in an input
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      const activeTag = document.activeElement?.tagName.toLowerCase();
      if (activeTag === 'input' || activeTag === 'textarea') return;

      if (e.code === 'Space') {
        e.preventDefault();
        onToggleMute();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [onToggleMute]);

  const handleSubmit = (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    if (prompt.trim()) {
      onSendCommand(prompt.trim(), selectedCodeModel);
      setPrompt('');
    }
  };

  const handleInputKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  const isBuilding =
    buildStage &&
    buildStage !== 'SUCCEEDED' &&
    buildStage !== 'FAILED' &&
    buildStage !== 'CANCELLED';

  return (
    <div
      style={{
        backgroundColor: 'var(--bg-elevated)',
        borderTop: '1px solid var(--border-subtle)',
        display: 'flex',
        flexDirection: 'column',
        zIndex: 40,
      }}
    >
      {/* Live Transcript Stream Overlay (appears during active conversation) */}
      {(userTranscript || aiTranscript) && (
        <div
          style={{
            padding: '8px 16px',
            backgroundColor: 'rgba(16, 11, 36, 0.95)',
            borderBottom: '1px solid var(--border-subtle)',
            display: 'flex',
            flexDirection: 'column',
            gap: '4px',
            fontSize: '13px',
          }}
        >
          {userTranscript && (
            <div style={{ display: 'flex', gap: '8px', color: 'var(--accent-blue)' }}>
              <span style={{ fontWeight: 600, fontFamily: 'var(--font-mono)' }}>You:</span>
              <span style={{ color: 'var(--text-primary)' }}>{userTranscript}</span>
            </div>
          )}
          {aiTranscript && (
            <div style={{ display: 'flex', gap: '8px', color: 'var(--accent-primary)' }}>
              <Volume2 size={15} color="var(--accent-primary)" style={{ marginTop: '2px' }} />
              <span style={{ fontWeight: 600, fontFamily: 'var(--font-mono)' }}>Yulya:</span>
              <span style={{ color: 'var(--text-primary)', fontStyle: 'italic' }}>{aiTranscript}</span>
            </div>
          )}
        </div>
      )}

      {/* Main Command & Voice Controls Row */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: '12px',
          padding: '10px 16px',
        }}
      >
        {/* Persistent Voice Mute/Unmute Toggle */}
        <button
          onClick={onToggleMute}
          title={isMuted ? 'Microphone is Muted (Press Space or Click)' : 'Microphone is Active (Press Space or Click to Mute)'}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
            backgroundColor: isMuted ? 'rgba(244, 63, 94, 0.15)' : 'rgba(52, 211, 153, 0.15)',
            border: `1px solid ${isMuted ? 'var(--accent-rose)' : 'var(--accent-green)'}`,
            color: isMuted ? 'var(--accent-rose)' : 'var(--accent-green)',
            padding: '8px 14px',
            borderRadius: '8px',
            cursor: 'pointer',
            fontSize: '13px',
            fontWeight: 600,
            whiteSpace: 'nowrap',
            transition: 'all 0.15s ease',
          }}
        >
          {isMuted ? <MicOff size={16} /> : <Mic size={16} />}
          <span>{isMuted ? 'Unmute Mic' : 'Mute Mic'}</span>
          <span
            style={{
              fontSize: '10px',
              fontFamily: 'var(--font-mono)',
              opacity: 0.7,
              backgroundColor: 'rgba(0,0,0,0.2)',
              padding: '1px 4px',
              borderRadius: '3px',
            }}
          >
            Space
          </span>
        </button>

        {/* Text Prompt Input Box */}
        <div
          style={{
            flex: 1,
            position: 'relative',
            display: 'flex',
            alignItems: 'center',
            backgroundColor: 'var(--bg-deepest)',
            border: '1px solid var(--border-subtle)',
            borderRadius: '8px',
            padding: '0 8px',
          }}
        >
          <textarea
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            onKeyDown={handleInputKeyDown}
            placeholder={
              isBuilding
                ? `Yulya is editing (${buildStage})... You can queue another request.`
                : 'Ask Yulya to change the game, fix bugs, or build new features... (Enter to send)'
            }
            rows={1}
            style={{
              flex: 1,
              backgroundColor: 'transparent',
              border: 'none',
              outline: 'none',
              color: 'var(--text-primary)',
              fontFamily: 'var(--font-sans)',
              fontSize: '13px',
              padding: '10px 4px',
              resize: 'none',
              maxHeight: '80px',
            }}
          />

          {/* Model Selector Pill */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '4px', marginRight: '6px' }}>
            <Cpu size={12} color="var(--text-tertiary)" />
            <select
              value={selectedCodeModel}
              onChange={(e) => onSelectCodeModel(e.target.value)}
              style={{
                backgroundColor: 'transparent',
                border: 'none',
                color: 'var(--text-secondary)',
                fontSize: '11px',
                fontFamily: 'var(--font-mono)',
                outline: 'none',
                cursor: 'pointer',
              }}
            >
              {codeModels.map((m) => (
                <option key={m.id} value={m.id} style={{ backgroundColor: 'var(--bg-elevated)', color: '#fff' }}>
                  {m.display_name}
                </option>
              ))}
            </select>
          </div>

          {/* Send Action */}
          <button
            onClick={() => handleSubmit()}
            disabled={!prompt.trim()}
            title="Send prompt"
            style={{
              backgroundColor: prompt.trim() ? 'var(--accent-primary)' : 'transparent',
              border: 'none',
              color: prompt.trim() ? '#ffffff' : 'var(--text-tertiary)',
              padding: '6px',
              borderRadius: '6px',
              cursor: prompt.trim() ? 'pointer' : 'default',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}
          >
            {isBuilding ? <Loader2 size={16} className="spinning" /> : <Send size={15} />}
          </button>
        </div>

        {/* Build Status Indicator */}
        {isBuilding && (
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              padding: '6px 12px',
              backgroundColor: 'rgba(251, 191, 36, 0.1)',
              border: '1px solid var(--accent-amber)',
              borderRadius: '6px',
              fontSize: '12px',
              color: 'var(--accent-amber)',
              fontFamily: 'var(--font-mono)',
              whiteSpace: 'nowrap',
            }}
          >
            <Loader2 size={13} style={{ animation: 'spin 1s linear infinite' }} />
            <span>{buildMessage || buildStage}</span>
          </div>
        )}
      </div>
    </div>
  );
};
