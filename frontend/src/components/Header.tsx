import React, { useState } from 'react';
import { Project, LiveSessionState, User } from '../types';
import {
  Code,
  Radio,
  Gamepad2,
  User as UserIcon,
  Settings,
  Share2,
  Plus,
  ChevronDown,
  Sparkles,
  Mic,
  MicOff,
} from 'lucide-react';

interface HeaderProps {
  currentProject: Project | null;
  projects: Project[];
  activeView: 'studio' | 'arcade' | 'profile';
  liveState: LiveSessionState;
  isMuted: boolean;
  currentUser: User | null;
  onSelectProject: (p: Project) => void;
  onNewProject: () => void;
  onSwitchView: (v: 'studio' | 'arcade' | 'profile') => void;
  onOpenSettings: () => void;
  onShare: () => void;
  onToggleMute: () => void;
}

export const Header: React.FC<HeaderProps> = ({
  currentProject,
  projects,
  activeView,
  liveState,
  isMuted,
  currentUser,
  onSelectProject,
  onNewProject,
  onSwitchView,
  onOpenSettings,
  onShare,
  onToggleMute,
}) => {
  const [dropdownOpen, setDropdownOpen] = useState(false);

  const getStatusColor = (state: LiveSessionState) => {
    switch (state) {
      case 'CONNECTED':
      case 'LISTENING':
        return '#34d399'; // green
      case 'SPEAKING':
        return '#38bdf8'; // blue
      case 'THINKING':
      case 'TOOL_RUNNING':
        return '#fbbf24'; // amber
      case 'CONNECTING':
      case 'FALLING_BACK':
        return '#8b5cf6'; // purple
      case 'ERROR':
        return '#f43f5e'; // red
      default:
        return '#65607a'; // gray
    }
  };

  return (
    <header
      style={{
        height: '48px',
        backgroundColor: 'var(--bg-base)',
        borderBottom: '1px solid var(--border-subtle)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '0 16px',
        userSelect: 'none',
        zIndex: 50,
      }}
    >
      {/* Left: Branding & Project Selector */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
        <div
          onClick={() => onSwitchView('studio')}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
            cursor: 'pointer',
            fontWeight: 700,
            fontSize: '15px',
            letterSpacing: '0.5px',
          }}
        >
          <span style={{ color: 'var(--accent-primary)', fontSize: '18px' }}>✦</span>
          <span>YULYA</span>
          <span
            style={{
              fontSize: '10px',
              padding: '2px 6px',
              backgroundColor: 'rgba(139, 92, 246, 0.15)',
              border: '1px solid var(--border-subtle)',
              borderRadius: '4px',
              color: 'var(--accent-primary)',
              fontFamily: 'var(--font-mono)',
            }}
          >
            V2 IDE
          </span>
        </div>

        {/* Project Selector Menu */}
        <div style={{ position: 'relative' }}>
          <button
            onClick={() => setDropdownOpen(!dropdownOpen)}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              backgroundColor: 'var(--bg-elevated)',
              border: '1px solid var(--border-subtle)',
              padding: '5px 10px',
              borderRadius: '6px',
              color: 'var(--text-primary)',
              fontSize: '13px',
              cursor: 'pointer',
              fontWeight: 500,
            }}
          >
            <Code size={14} color="var(--accent-primary)" />
            <span>{currentProject?.title || 'Select Project'}</span>
            <ChevronDown size={12} color="var(--text-secondary)" />
          </button>

          {dropdownOpen && (
            <div
              style={{
                position: 'absolute',
                top: '100%',
                left: 0,
                marginTop: '4px',
                width: '240px',
                backgroundColor: 'var(--bg-elevated)',
                border: '1px solid var(--border-active)',
                borderRadius: '8px',
                boxShadow: '0 8px 24px rgba(0,0,0,0.6)',
                zIndex: 100,
                padding: '4px',
              }}
            >
              <div
                style={{
                  fontSize: '11px',
                  color: 'var(--text-tertiary)',
                  padding: '6px 8px',
                  fontWeight: 600,
                  textTransform: 'uppercase',
                }}
              >
                Repositories
              </div>
              {projects.map((p) => (
                <div
                  key={p.slug}
                  onClick={() => {
                    onSelectProject(p);
                    setDropdownOpen(false);
                  }}
                  style={{
                    padding: '8px',
                    borderRadius: '4px',
                    cursor: 'pointer',
                    fontSize: '13px',
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    backgroundColor: p.slug === currentProject?.slug ? 'rgba(139, 92, 246, 0.15)' : 'transparent',
                    color: p.slug === currentProject?.slug ? 'var(--accent-primary)' : 'var(--text-primary)',
                  }}
                >
                  <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {p.title}
                  </span>
                  <span style={{ fontSize: '11px', color: 'var(--text-tertiary)', fontFamily: 'var(--font-mono)' }}>
                    /{p.slug}
                  </span>
                </div>
              ))}
              <div
                style={{
                  borderTop: '1px solid var(--border-subtle)',
                  marginTop: '4px',
                  paddingTop: '4px',
                }}
              >
                <button
                  onClick={() => {
                    onNewProject();
                    setDropdownOpen(false);
                  }}
                  style={{
                    width: '100%',
                    padding: '8px',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '6px',
                    backgroundColor: 'transparent',
                    border: 'none',
                    color: 'var(--accent-primary)',
                    fontSize: '13px',
                    cursor: 'pointer',
                    fontWeight: 600,
                  }}
                >
                  <Plus size={14} />
                  <span>Create New Project</span>
                </button>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Center: Live Voice Pill & Status */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
            backgroundColor: 'var(--bg-elevated)',
            border: '1px solid var(--border-subtle)',
            padding: '4px 12px',
            borderRadius: '20px',
            fontSize: '12px',
            fontFamily: 'var(--font-mono)',
          }}
        >
          <span
            style={{
              width: '8px',
              height: '8px',
              borderRadius: '50%',
              backgroundColor: getStatusColor(liveState),
              boxShadow: `0 0 8px ${getStatusColor(liveState)}`,
              display: 'inline-block',
            }}
          />
          <span style={{ color: 'var(--text-secondary)' }}>Live Voice:</span>
          <span style={{ fontWeight: 600, color: getStatusColor(liveState) }}>
            {liveState}
          </span>

          {liveState === 'CONNECTED' && (
            <button
              onClick={onToggleMute}
              title={isMuted ? 'Microphone Muted (Click to Unmute)' : 'Microphone Live (Click to Mute)'}
              style={{
                marginLeft: '6px',
                display: 'flex',
                alignItems: 'center',
                gap: '4px',
                backgroundColor: isMuted ? 'rgba(244, 63, 94, 0.15)' : 'rgba(52, 211, 153, 0.15)',
                border: `1px solid ${isMuted ? 'var(--accent-rose)' : 'var(--accent-green)'}`,
                color: isMuted ? 'var(--accent-rose)' : 'var(--accent-green)',
                padding: '2px 8px',
                borderRadius: '12px',
                cursor: 'pointer',
                fontSize: '11px',
                fontWeight: 600,
              }}
            >
              {isMuted ? <MicOff size={12} /> : <Mic size={12} />}
              <span>{isMuted ? 'MUTED' : 'UNMUTED'}</span>
            </button>
          )}
        </div>
      </div>

      {/* Right: View Switcher, Share & Profile */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
        <button
          onClick={() => onSwitchView('studio')}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '5px',
            backgroundColor: activeView === 'studio' ? 'var(--bg-surface)' : 'transparent',
            border: 'none',
            color: activeView === 'studio' ? 'var(--accent-primary)' : 'var(--text-secondary)',
            padding: '6px 10px',
            borderRadius: '6px',
            cursor: 'pointer',
            fontSize: '12px',
            fontWeight: 600,
          }}
        >
          <Code size={13} />
          <span>IDE</span>
        </button>

        <button
          onClick={() => onSwitchView('arcade')}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '5px',
            backgroundColor: activeView === 'arcade' ? 'var(--bg-surface)' : 'transparent',
            border: 'none',
            color: activeView === 'arcade' ? 'var(--accent-primary)' : 'var(--text-secondary)',
            padding: '6px 10px',
            borderRadius: '6px',
            cursor: 'pointer',
            fontSize: '12px',
            fontWeight: 600,
          }}
        >
          <Gamepad2 size={13} />
          <span>Arcade</span>
        </button>

        <button
          onClick={() => onSwitchView('profile')}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '5px',
            backgroundColor: activeView === 'profile' ? 'var(--bg-surface)' : 'transparent',
            border: 'none',
            color: activeView === 'profile' ? 'var(--accent-primary)' : 'var(--text-secondary)',
            padding: '6px 10px',
            borderRadius: '6px',
            cursor: 'pointer',
            fontSize: '12px',
            fontWeight: 600,
          }}
        >
          <UserIcon size={13} />
          <span>Portfolio</span>
        </button>

        <div style={{ width: '1px', height: '16px', backgroundColor: 'var(--border-subtle)', margin: '0 4px' }} />

        <button
          onClick={onShare}
          title="Copy Playable Link"
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '4px',
            backgroundColor: 'var(--bg-elevated)',
            border: '1px solid var(--border-subtle)',
            color: 'var(--text-primary)',
            padding: '5px 10px',
            borderRadius: '6px',
            cursor: 'pointer',
            fontSize: '12px',
            fontWeight: 500,
          }}
        >
          <Share2 size={13} color="var(--accent-blue)" />
          <span>Share</span>
        </button>

        <button
          onClick={onOpenSettings}
          title="Settings & API Key"
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            backgroundColor: 'var(--bg-elevated)',
            border: '1px solid var(--border-subtle)',
            color: 'var(--text-primary)',
            width: '28px',
            height: '28px',
            borderRadius: '6px',
            cursor: 'pointer',
          }}
        >
          <Settings size={14} color="var(--text-secondary)" />
        </button>
      </div>
    </header>
  );
};
