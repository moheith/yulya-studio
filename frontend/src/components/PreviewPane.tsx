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
  width?: number;
  onRestart: () => void;
  onSendScreenshareFrame: (base64Data: string) => void;
  onRequestFixError: (errorDetails: string) => void;
}

export const PreviewPane: React.FC<PreviewPaneProps> = ({
  username,
  slug,
  previewKey,
  width,
  onRestart,
  onSendScreenshareFrame,
  onRequestFixError,
}) => {
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const mediaStreamRef = useRef<MediaStream | null>(null);
  const videoElementRef = useRef<HTMLVideoElement | null>(null);
  const captureIntervalRef = useRef<any>(null);

  const [isFullscreen, setIsFullscreen] = useState(false);
  const [visionActive, setVisionActive] = useState(false);
  const [runtimeError, setRuntimeError] = useState<string | null>(null);

  const previewUrl = `/${encodeURIComponent(username)}/${encodeURIComponent(slug)}/`;

  const stopVision = () => {
    if (captureIntervalRef.current) {
      clearInterval(captureIntervalRef.current);
      captureIntervalRef.current = null;
    }
    if (mediaStreamRef.current) {
      mediaStreamRef.current.getTracks().forEach((track) => track.stop());
      mediaStreamRef.current = null;
    }
    if (videoElementRef.current) {
      videoElementRef.current.srcObject = null;
      videoElementRef.current = null;
    }
    setVisionActive(false);
  };

  const captureFrame = () => {
    const video = videoElementRef.current;
    if (!video || video.readyState < 2 || video.videoWidth === 0 || video.videoHeight === 0) {
      return;
    }

    try {
      const canvas = document.createElement('canvas');
      let w = video.videoWidth;
      let h = video.videoHeight;
      const maxDim = 1280;
      if (w > maxDim || h > maxDim) {
        if (w > h) {
          h = Math.round((h * maxDim) / w);
          w = maxDim;
        } else {
          w = Math.round((w * maxDim) / h);
          h = maxDim;
        }
      }
      canvas.width = w;
      canvas.height = h;
      const ctx = canvas.getContext('2d');
      if (!ctx) return;
      ctx.drawImage(video, 0, 0, w, h);
      const dataUrl = canvas.toDataURL('image/jpeg', 0.7);
      onSendScreenshareFrame(dataUrl);
    } catch (err) {
      console.warn('Frame capture error:', err);
    }
  };

  const startVision = async () => {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getDisplayMedia) {
      alert('Screen capture is not supported in this browser.');
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getDisplayMedia({
        video: {
          frameRate: { ideal: 1, max: 2 },
        },
        audio: false,
      });
      mediaStreamRef.current = stream;
      const track = stream.getVideoTracks()[0];
      if (!track) {
        throw new Error('No video track available');
      }

      track.onended = () => {
        stopVision();
      };

      const video = document.createElement('video');
      video.srcObject = stream;
      video.muted = true;
      video.playsInline = true;
      await video.play();
      videoElementRef.current = video;

      setVisionActive(true);

      // Capture initial frame after short delay for video to buffer
      setTimeout(captureFrame, 200);

      // Bounded 1 FPS capture interval
      captureIntervalRef.current = setInterval(captureFrame, 1000);
    } catch (err: any) {
      if (err.name !== 'NotAllowedError') {
        console.error('Failed to start vision screen share:', err);
      }
      stopVision();
    }
  };

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      stopVision();
    };
  }, []);

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
        width: width !== undefined ? `${width}px` : '420px',
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
            onClick={() => (visionActive ? stopVision() : startVision())}
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
