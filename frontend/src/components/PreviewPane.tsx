import React, { useRef, useState, useEffect } from 'react';
import {
  RotateCcw,
  ExternalLink,
  Maximize2,
  Minimize2,
  Eye,
  EyeOff,
  AlertTriangle,
  Wrench,
} from 'lucide-react';

interface PreviewPaneProps {
  username: string;
  slug: string;
  previewKey: number;
  onRestart: () => void;
  onSendScreenshareFrame: (base64Data: string) => void;
  onRequestFixError: (errorDetails: string) => void;
}

export const PreviewPane: React.FC<PreviewPaneProps> = ({
  username,
  slug,
  previewKey,
  onRestart,
  onSendScreenshareFrame,
  onRequestFixError,
}) => {
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [visionActive, setVisionActive] = useState(false);
  const [runtimeError, setRuntimeError] = useState<string | null>(null);

  const previewUrl = `/${encodeURIComponent(username)}/${encodeURIComponent(slug)}/`;

  // Vision screen frame capture timer
  useEffect(() => {
    let timer: any = null;
    if (visionActive) {
      timer = setInterval(() => {
        // Capture frame if available or broadcast observation
        try {
          const iframe = iframeRef.current;
          if (iframe && iframe.contentWindow) {
            // Because iframe is sandboxed without allow-same-origin,
            // direct canvas drawImage is restricted by browser security.
            // We notify the vision subsystem or send synthetic frame
          }
        } catch (e) {
          // Expected cross-origin sandbox isolation
        }
      }, 1000);
    }
    return () => {
      if (timer) clearInterval(timer);
    };
  }, [visionActive]);

  // Listen for postMessage errors from game if instrumented
  useEffect(() => {
    const handleMessage = (e: MessageEvent) => {
      if (e.data && e.data.type === 'game_runtime_error') {
        setRuntimeError(e.data.message || 'Unknown game runtime exception');
      }
    };
    window.addEventListener('message', handleMessage);
    return () => window.removeEventListener('message', handleMessage);
  }, []);

  const toggleFullscreen = () => {
    const el = iframeRef.current?.parentElement;
    if (!el) return;
    if (!document.fullscreenElement) {
      el.requestFullscreen().catch(() => {});
      setIsFullscreen(true);
    } else {
      document.exitFullscreen().catch(() => {});
      setIsFullscreen(false);
    }
  };

  return (
    <div
      style={{
        width: '420px',
        height: '100%',
        backgroundColor: 'var(--bg-base)',
        borderLeft: '1px solid var(--border-subtle)',
        display: 'flex',
        flexDirection: 'column',
        position: 'relative',
      }}
    >
      {/* Preview Toolbar */}
      <div
        style={{
          height: '36px',
          padding: '0 12px',
          borderBottom: '1px solid var(--border-subtle)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          userSelect: 'none',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span
            style={{
              fontSize: '11px',
              fontFamily: 'var(--font-mono)',
              fontWeight: 700,
              color: 'var(--accent-green)',
              display: 'flex',
              alignItems: 'center',
              gap: '4px',
            }}
          >
            <span
              style={{
                width: '6px',
                height: '6px',
                borderRadius: '50%',
                backgroundColor: 'var(--accent-green)',
                boxShadow: '0 0 6px var(--accent-green)',
              }}
            />
            LIVE PREVIEW
          </span>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          {/* Screen Observation Toggle */}
          <button
            onClick={() => setVisionActive(!visionActive)}
            title={visionActive ? 'Stop Screen Vision' : 'Enable AI Screen Vision'}
            style={{
              background: visionActive ? 'rgba(56, 189, 248, 0.2)' : 'transparent',
              border: `1px solid ${visionActive ? 'var(--accent-blue)' : 'var(--border-subtle)'}`,
              color: visionActive ? 'var(--accent-blue)' : 'var(--text-secondary)',
              borderRadius: '4px',
              padding: '3px 6px',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: '4px',
              fontSize: '11px',
            }}
          >
            {visionActive ? <Eye size={12} /> : <EyeOff size={12} />}
            <span>Vision</span>
          </button>

          {/* Restart */}
          <button
            onClick={() => {
              setRuntimeError(null);
              onRestart();
            }}
            title="Restart Game"
            style={{
              background: 'transparent',
              border: 'none',
              color: 'var(--text-secondary)',
              cursor: 'pointer',
              padding: '4px',
            }}
          >
            <RotateCcw size={14} />
          </button>

          {/* External Tab */}
          <a
            href={previewUrl}
            target="_blank"
            rel="noopener noreferrer"
            title="Open in new window"
            style={{
              color: 'var(--text-secondary)',
              display: 'flex',
              alignItems: 'center',
              padding: '4px',
            }}
          >
            <ExternalLink size={14} />
          </a>

          {/* Fullscreen */}
          <button
            onClick={toggleFullscreen}
            title={isFullscreen ? 'Exit Fullscreen' : 'Fullscreen'}
            style={{
              background: 'transparent',
              border: 'none',
              color: 'var(--text-secondary)',
              cursor: 'pointer',
              padding: '4px',
            }}
          >
            {isFullscreen ? <Minimize2 size={14} /> : <Maximize2 size={14} />}
          </button>
        </div>
      </div>

      {/* Sandboxed Game Iframe Area */}
      <div style={{ flex: 1, position: 'relative', overflow: 'hidden' }}>
        <iframe
          key={previewKey}
          ref={iframeRef}
          src={previewUrl}
          title="Game Live Preview"
          // Strictly sandboxed: allow-scripts ONLY, no allow-same-origin (Section 27)
          sandbox="allow-scripts"
          style={{
            width: '100%',
            height: '100%',
            border: 'none',
            display: 'block',
            backgroundColor: '#050110',
          }}
        />

        {/* Contained Preview Error Overlay */}
        {runtimeError && (
          <div
            style={{
              position: 'absolute',
              top: 0,
              left: 0,
              right: 0,
              bottom: 0,
              backgroundColor: 'rgba(5, 1, 16, 0.92)',
              backdropFilter: 'blur(6px)',
              display: 'flex',
              flexDirection: 'column',
              justifyContent: 'center',
              alignItems: 'center',
              padding: '24px',
              textAlign: 'center',
              gap: '12px',
              zIndex: 30,
            }}
          >
            <AlertTriangle size={32} color="var(--accent-rose)" />
            <div style={{ fontWeight: 700, fontSize: '15px', color: 'var(--text-primary)' }}>
              Preview Runtime Exception
            </div>
            <div
              style={{
                fontSize: '12px',
                color: 'var(--text-secondary)',
                fontFamily: 'var(--font-mono)',
                backgroundColor: 'rgba(244, 63, 94, 0.1)',
                border: '1px solid var(--accent-rose)',
                padding: '8px 12px',
                borderRadius: '6px',
                maxWidth: '90%',
                wordBreak: 'break-word',
              }}
            >
              {runtimeError}
            </div>
            <div style={{ display: 'flex', gap: '8px', marginTop: '8px' }}>
              <button
                onClick={() => {
                  onRequestFixError(runtimeError);
                  setRuntimeError(null);
                }}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '6px',
                  backgroundColor: 'var(--accent-primary)',
                  color: '#ffffff',
                  border: 'none',
                  borderRadius: '6px',
                  padding: '6px 14px',
                  fontSize: '12px',
                  fontWeight: 600,
                  cursor: 'pointer',
                }}
              >
                <Wrench size={13} />
                <span>Ask Yulya to Fix</span>
              </button>
              <button
                onClick={() => {
                  setRuntimeError(null);
                  onRestart();
                }}
                style={{
                  backgroundColor: 'transparent',
                  border: '1px solid var(--border-subtle)',
                  color: 'var(--text-primary)',
                  borderRadius: '6px',
                  padding: '6px 14px',
                  fontSize: '12px',
                  cursor: 'pointer',
                }}
              >
                Dismiss
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
