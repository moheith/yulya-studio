import React, { useState, useEffect, useRef, useCallback } from 'react';
import {
  Project,
  LiveSessionState,
  BuildStage,
  ModelEntry,
  ActivityLog,
  ToastItem,
  User,
} from './types';
import {
  fetchMyProjects,
  createProject,
  deleteProject,
  fetchProjectFiles,
  saveProjectFile,
  modifyProject,
  publishRelease,
  fetchCommunityProjects,
  fetchModels,
  fetchCurrentUser,
} from './services/api';
import { AudioStreamer } from './services/audioStreamer';
import { Header } from './components/Header';
import { FileTree } from './components/FileTree';
import { MonacoEditor } from './components/MonacoEditor';
import { PreviewPane } from './components/PreviewPane';
import { Terminal } from './components/Terminal';
import { VoiceAndChatBar } from './components/VoiceAndChatBar';
import { ArcadeView } from './components/ArcadeView';
import { PortfolioView } from './components/PortfolioView';
import { SettingsModal } from './components/SettingsModal';
import { ToastContainer } from './components/ToastContainer';

export const App: React.FC = () => {
  // Navigation & View
  const [activeView, setActiveView] = useState<'studio' | 'arcade' | 'profile'>('studio');

  // User & Projects
  const [currentUser, setCurrentUser] = useState<User | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [currentProject, setCurrentProject] = useState<Project | null>(null);
  const [communityProjects, setCommunityProjects] = useState<Project[]>([]);

  // Files & Editor
  const [files, setFiles] = useState<Record<string, string>>({});
  const [openTabs, setOpenTabs] = useState<string[]>(['index.html', 'style.css', 'app.js']);
  const [activeFile, setActiveFile] = useState<string>('app.js');
  const [dirtyFiles, setDirtyFiles] = useState<Set<string>>(new Set());
  const [diffView, setDiffView] = useState<{ original: string; modified: string; fileName: string } | null>(null);
  const [previewKey, setPreviewKey] = useState<number>(0);

  // Live Voice & Transcripts
  const [liveState, setLiveState] = useState<LiveSessionState>('DISCONNECTED');
  const [isMuted, setIsMuted] = useState<boolean>(false);
  const [userTranscript, setUserTranscript] = useState<string>('');
  const [aiTranscript, setAiTranscript] = useState<string>('');

  // Build Engine & Models
  const [buildStage, setBuildStage] = useState<BuildStage | null>(null);
  const [buildMessage, setBuildMessage] = useState<string | null>(null);
  const [liveModels, setLiveModels] = useState<ModelEntry[]>([]);
  const [codeModels, setCodeModels] = useState<ModelEntry[]>([]);
  const [selectedLiveModel, setSelectedLiveModel] = useState<string>('gemini-3.8-live');
  const [selectedCodeModel, setSelectedCodeModel] = useState<string>('gemini-3.8-flash');

  // Logs & Toasts
  const [logs, setLogs] = useState<ActivityLog[]>([]);
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const [settingsOpen, setSettingsOpen] = useState(false);

  // Resizable Panels State
  const [leftWidth, setLeftWidth] = useState<number>(220);
  const [rightWidth, setRightWidth] = useState<number>(420);
  const [terminalHeight, setTerminalHeight] = useState<number>(140);
  const [resizing, setResizing] = useState<'left' | 'right' | 'terminal' | null>(null);

  const startResizeLeft = (e: React.MouseEvent) => {
    e.preventDefault();
    setResizing('left');
  };

  const startResizeRight = (e: React.MouseEvent) => {
    e.preventDefault();
    setResizing('right');
  };

  const startResizeTerminal = (e: React.MouseEvent) => {
    e.preventDefault();
    setResizing('terminal');
  };

  useEffect(() => {
    if (!resizing) return;

    const handleMouseMove = (e: MouseEvent) => {
      if (resizing === 'left') {
        const newW = Math.max(160, Math.min(e.clientX, 500));
        setLeftWidth(newW);
      } else if (resizing === 'right') {
        const newW = Math.max(280, Math.min(window.innerWidth - e.clientX, 800));
        setRightWidth(newW);
      } else if (resizing === 'terminal') {
        const chatBarHeight = 52;
        const newH = Math.max(70, Math.min(window.innerHeight - e.clientY - chatBarHeight, 500));
        setTerminalHeight(newH);
      }
    };

    const handleMouseUp = () => {
      setResizing(null);
    };

    window.addEventListener('mousemove', handleMouseMove);
    window.addEventListener('mouseup', handleMouseUp);
    return () => {
      window.removeEventListener('mousemove', handleMouseMove);
      window.removeEventListener('mouseup', handleMouseUp);
    };
  }, [resizing]);

  // References
  const wsRef = useRef<WebSocket | null>(null);
  const audioStreamerRef = useRef<AudioStreamer | null>(null);

  const addLog = useCallback((message: string, level: ActivityLog['level'] = 'info') => {
    const newLog: ActivityLog = {
      id: `${Date.now()}_${Math.random()}`,
      timestamp: new Date().toTimeString().slice(0, 8),
      level,
      message,
    };
    setLogs((prev) => [...prev, newLog]);
  }, []);

  const showToast = useCallback((message: string, type: ToastItem['type'] = 'info') => {
    const id = `${Date.now()}_${Math.random()}`;
    setToasts((prev) => [...prev, { id, message, type }]);
    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, 4000);
  }, []);

  // 1. Initial Load: User, Models, Projects, and Gallery
  useEffect(() => {
    const initData = async () => {
      try {
        const userRes = await fetchCurrentUser();
        if (userRes.authenticated && userRes.user) {
          setCurrentUser({
            id: userRes.user.id,
            username: userRes.user.username,
            display_name: userRes.user.display_name || userRes.user.username,
            avatar: userRes.user.avatar,
          });
        }
      } catch (err) {
        console.warn('Could not load current user:', err);
      }

      try {
        const modelData = await fetchModels();
        if (modelData.live_models) setLiveModels(modelData.live_models);
        if (modelData.code_models) setCodeModels(modelData.code_models);
      } catch (err) {
        console.warn('Could not load models list:', err);
      }

      try {
        const commData = await fetchCommunityProjects();
        if (commData.projects) setCommunityProjects(commData.projects);
      } catch (err) {
        console.warn('Could not load community arcade:', err);
      }

      try {
        const projData = await fetchMyProjects();
        if (projData.projects && projData.projects.length > 0) {
          setProjects(projData.projects);
          setCurrentProject(projData.projects[0]);
        } else {
          // Auto initialize starter project
          const created = await createProject('Neon Dodge', 'Cyberpunk dodging arcade game');
          if (created.project) {
            setProjects([created.project]);
            setCurrentProject(created.project);
          }
        }
      } catch (err) {
        addLog('Running in offline / local development mode.', 'warning');
      }
    };
    initData();
  }, [addLog]);

  // 2. Load Project Files when currentProject changes
  const loadFiles = useCallback(async (slug: string) => {
    try {
      const data = await fetchProjectFiles(slug);
      if (data.files) {
        setFiles(data.files);
        const keys = Object.keys(data.files);
        if (keys.length > 0 && !keys.includes(activeFile)) {
          setActiveFile(keys[0]);
        }
      }
    } catch (err: any) {
      addLog(`Failed to load project files: ${err.message}`, 'error');
    }
  }, [activeFile, addLog]);

  useEffect(() => {
    if (currentProject) {
      loadFiles(currentProject.slug);
      setPreviewKey((k) => k + 1);
      addLog(`Opened repository: ${currentProject.title} (/${currentProject.slug})`, 'info');
    }
  }, [currentProject?.slug, loadFiles, addLog]);

  // 3. Audio Streamer Initialization
  useEffect(() => {
    const streamer = new AudioStreamer((pcmB64) => {
      if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN && !isMuted) {
        wsRef.current.send(
          JSON.stringify({
            type: 'audio_chunk',
            pcm: pcmB64,
          })
        );
      }
    });
    audioStreamerRef.current = streamer;

    return () => {
      streamer.stopMicrophone();
    };
  }, [isMuted]);

  // 4. Authoritative WebSocket Connection
  useEffect(() => {
    if (!currentProject) return;

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws/studio?slug=${encodeURIComponent(currentProject.slug)}`;

    addLog(`Connecting to Studio WebSocket (${currentProject.slug})...`, 'info');
    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onopen = () => {
      addLog('Studio WebSocket connected.', 'success');
      // Connect live session
      ws.send(JSON.stringify({ type: 'connect_live', model: selectedLiveModel }));
      audioStreamerRef.current?.startMicrophone();
    };

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        handleWsMessage(msg);
      } catch (e) {
        console.warn('WS message parse error:', e);
      }
    };

    ws.onclose = () => {
      setLiveState('DISCONNECTED');
      addLog('Studio WebSocket disconnected.', 'warning');
    };

    ws.onerror = (err) => {
      console.warn('Studio WebSocket error:', err);
    };

    // Heartbeat every 30s
    const heartbeatTimer = setInterval(() => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'heartbeat' }));
      }
    }, 30000);

    return () => {
      clearInterval(heartbeatTimer);
      ws.close();
    };
  }, [currentProject?.slug, selectedLiveModel, addLog]);

  // Handle Studio WebSocket Events
  const handleWsMessage = (msg: any) => {
    switch (msg.type) {
      case 'live_session_state':
        setLiveState(msg.state);
        if (msg.reason) addLog(`Live session: ${msg.state} (${msg.reason})`, 'ai');
        break;

      case 'mic_state':
        setIsMuted(msg.is_muted);
        audioStreamerRef.current?.setMuted(msg.is_muted);
        break;

      case 'user_transcript_delta':
        setUserTranscript((prev) => prev + msg.delta);
        break;

      case 'ai_transcript_delta':
        setAiTranscript((prev) => prev + msg.delta);
        break;

      case 'ai_turn_complete':
        addLog(`Yulya: ${aiTranscript}`, 'ai');
        setAiTranscript('');
        setUserTranscript('');
        break;

      case 'ai_audio_chunk':
        if (msg.pcm && audioStreamerRef.current) {
          audioStreamerRef.current.playPcmChunk(msg.pcm, msg.rate || 24000);
        }
        break;

      case 'ai_interrupted':
        audioStreamerRef.current?.resetPlayback();
        setAiTranscript('');
        addLog('Voice assistant interrupted by creator.', 'info');
        break;

      case 'build_event':
        const be = msg.event;
        setBuildStage(be.stage);
        setBuildMessage(be.message);
        addLog(`[BUILD ${be.stage}] ${be.message}`, be.stage === 'FAILED' ? 'error' : 'info');

        if (be.stage === 'SUCCEEDED' || be.stage === 'PREVIEW_READY') {
          showToast('Game synthesized successfully!', 'success');
          if (currentProject) loadFiles(currentProject.slug);
          setPreviewKey((k) => k + 1);
        } else if (be.stage === 'FAILED') {
          showToast(`Build failed: ${be.error || be.message}`, 'error');
        }
        break;

      case 'live_error':
        showToast(msg.message, 'error');
        addLog(`Live Error: ${msg.message}`, 'error');
        break;

      default:
        break;
    }
  };

  // Toggle Mute Action
  const handleToggleMute = () => {
    const newMuted = !isMuted;
    setIsMuted(newMuted);
    audioStreamerRef.current?.setMuted(newMuted);
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: newMuted ? 'mute_audio' : 'unmute_audio' }));
    }
    showToast(newMuted ? 'Microphone muted' : 'Microphone unmuted', 'info');
  };

  // Dispatch Command to Game Coding Agent
  const handleSendCommand = (prompt: string, modelId?: string) => {
    if (!currentProject) return;
    addLog(`User: "${prompt}"`, 'info');
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'command', prompt }));
    } else {
      // Fallback REST modify
      modifyProject(currentProject.slug, prompt, modelId).catch((err) => {
        showToast(err.message, 'error');
      });
    }
  };

  // File Editor Handlers
  const handleSelectFile = (fileName: string) => {
    setActiveFile(fileName);
    if (!openTabs.includes(fileName)) {
      setOpenTabs((prev) => [...prev, fileName]);
    }
  };

  const handleCloseTab = (fileName: string) => {
    const nextTabs = openTabs.filter((t) => t !== fileName);
    setOpenTabs(nextTabs);
    if (activeFile === fileName && nextTabs.length > 0) {
      setActiveFile(nextTabs[nextTabs.length - 1]);
    }
  };

  const handleChangeContent = (fileName: string, newContent: string) => {
    setFiles((prev) => ({ ...prev, [fileName]: newContent }));
    setDirtyFiles((prev) => new Set(prev).add(fileName));
  };

  const handleSaveFile = async (fileName: string) => {
    if (!currentProject) return;
    try {
      await saveProjectFile(currentProject.slug, fileName, files[fileName] || '');
      setDirtyFiles((prev) => {
        const next = new Set(prev);
        next.delete(fileName);
        return next;
      });
      setPreviewKey((k) => k + 1);
      showToast(`Saved '${fileName}'`, 'success');
      addLog(`Saved file: ${fileName}`, 'info');
    } catch (err: any) {
      showToast(err.message || 'Failed to save file', 'error');
    }
  };

  const handleCreateFile = async (fileName: string) => {
    if (!currentProject) return;
    try {
      await saveProjectFile(currentProject.slug, fileName, '');
      setFiles((prev) => ({ ...prev, [fileName]: '' }));
      handleSelectFile(fileName);
      showToast(`Created file '${fileName}'`, 'success');
    } catch (err: any) {
      showToast(err.message || 'Failed to create file', 'error');
    }
  };

  const handleDeleteFile = async (fileName: string) => {
    // Basic file deletion
    setFiles((prev) => {
      const next = { ...prev };
      delete next[fileName];
      return next;
    });
    handleCloseTab(fileName);
    showToast(`Deleted '${fileName}'`, 'info');
  };

  // Project Creation
  const handleNewProject = async () => {
    const title = window.prompt('Enter game title:');
    if (title && title.trim()) {
      try {
        const res = await createProject(title.trim());
        if (res.project) {
          setProjects((prev) => [res.project, ...prev]);
          setCurrentProject(res.project);
          setActiveView('studio');
          showToast(`Created project '${title}'`, 'success');
        }
      } catch (err: any) {
        showToast(err.message, 'error');
      }
    }
  };

  // Project Deletion
  const handleDeleteProject = async (slug: string) => {
    try {
      await deleteProject(slug);
      const remaining = projects.filter((p) => p.slug !== slug);
      setProjects(remaining);
      if (currentProject?.slug === slug) {
        setCurrentProject(remaining[0] || null);
      }
      showToast(`Deleted project '/${slug}'`, 'info');
    } catch (err: any) {
      showToast(err.message, 'error');
    }
  };

  // Publish Release
  const handlePublishRelease = async (slug: string) => {
    try {
      const res = await publishRelease(slug);
      showToast(res.message || 'Game published successfully!', 'success');
      addLog(`Published release for /${slug}: ${res.public_url}`, 'success');
    } catch (err: any) {
      showToast(err.message, 'error');
    }
  };

  // Share Playable URL
  const handleShare = () => {
    if (!currentProject) return;
    const url = `${window.location.origin}/${encodeURIComponent(currentUser?.username || 'creator')}/${encodeURIComponent(currentProject.slug)}/`;
    navigator.clipboard.writeText(url).then(() => {
      showToast('Playable game link copied to clipboard!', 'success');
    });
  };

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        height: '100vh',
        width: '100vw',
        overflow: 'hidden',
        backgroundColor: 'var(--bg-deepest)',
      }}
    >
      {/* Top Header */}
      <Header
        currentProject={currentProject}
        projects={projects}
        activeView={activeView}
        liveState={liveState}
        isMuted={isMuted}
        currentUser={currentUser}
        onSelectProject={(p) => setCurrentProject(p)}
        onNewProject={handleNewProject}
        onSwitchView={(v) => setActiveView(v)}
        onOpenSettings={() => setSettingsOpen(true)}
        onShare={handleShare}
        onToggleMute={handleToggleMute}
      />

      {/* Main Surface View */}
      {activeView === 'arcade' ? (
        <ArcadeView
          projects={communityProjects.length > 0 ? communityProjects : projects}
          onPlayInStudio={(p) => {
            setCurrentProject(p);
            setActiveView('studio');
          }}
        />
      ) : activeView === 'profile' ? (
        <PortfolioView
          currentUser={currentUser}
          projects={projects}
          onOpenProject={(p) => {
            setCurrentProject(p);
            setActiveView('studio');
          }}
          onNewProject={handleNewProject}
          onDeleteProject={handleDeleteProject}
          onPublishRelease={handlePublishRelease}
        />
      ) : (
        /* Studio IDE View */
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', position: 'relative' }}>
          {/* Global transparent drag overlay to prevent iframe stealing mouse events */}
          {resizing && (
            <div
              style={{
                position: 'fixed',
                top: 0,
                left: 0,
                right: 0,
                bottom: 0,
                zIndex: 9999,
                cursor: resizing === 'terminal' ? 'row-resize' : 'col-resize',
                userSelect: 'none',
              }}
            />
          )}

          <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>
            {/* Left: File Explorer */}
            <FileTree
              files={files}
              activeFile={activeFile}
              dirtyFiles={dirtyFiles}
              width={leftWidth}
              onSelectFile={handleSelectFile}
              onCreateFile={handleCreateFile}
              onDeleteFile={handleDeleteFile}
              onDownloadZip={() => {
                if (currentProject) {
                  window.open(`/api/download-zip/${currentUser?.username || 'creator'}/${currentProject.slug}`, '_blank');
                }
              }}
            />

            {/* Draggable Vertical Splitter: FileTree <-> MonacoEditor */}
            <div
              onMouseDown={startResizeLeft}
              style={{
                width: '4px',
                cursor: 'col-resize',
                backgroundColor: resizing === 'left' ? 'var(--accent-primary)' : 'var(--border-subtle)',
                transition: 'background-color 0.15s ease',
                zIndex: 10,
                flexShrink: 0,
              }}
              onMouseEnter={(e) => {
                if (!resizing) (e.currentTarget as HTMLElement).style.backgroundColor = 'var(--accent-primary)';
              }}
              onMouseLeave={(e) => {
                if (resizing !== 'left') (e.currentTarget as HTMLElement).style.backgroundColor = 'var(--border-subtle)';
              }}
            />

            {/* Center: Monaco Editor & Tabs */}
            <MonacoEditor
              openTabs={openTabs}
              activeFile={activeFile}
              files={files}
              dirtyFiles={dirtyFiles}
              diffView={diffView}
              onSelectTab={setActiveFile}
              onCloseTab={handleCloseTab}
              onChangeContent={handleChangeContent}
              onSaveFile={handleSaveFile}
              onCloseDiff={() => setDiffView(null)}
            />

            {/* Draggable Vertical Splitter: MonacoEditor <-> PreviewPane */}
            <div
              onMouseDown={startResizeRight}
              style={{
                width: '4px',
                cursor: 'col-resize',
                backgroundColor: resizing === 'right' ? 'var(--accent-primary)' : 'var(--border-subtle)',
                transition: 'background-color 0.15s ease',
                zIndex: 10,
                flexShrink: 0,
              }}
              onMouseEnter={(e) => {
                if (!resizing) (e.currentTarget as HTMLElement).style.backgroundColor = 'var(--accent-primary)';
              }}
              onMouseLeave={(e) => {
                if (resizing !== 'right') (e.currentTarget as HTMLElement).style.backgroundColor = 'var(--border-subtle)';
              }}
            />

            {/* Right: Live Sandboxed Game Preview */}
            <PreviewPane
              username={currentUser?.username || 'creator'}
              slug={currentProject?.slug || 'neon-dodge'}
              previewKey={previewKey}
              width={rightWidth}
              onRestart={() => setPreviewKey((k) => k + 1)}
              onSendScreenshareFrame={(b64) => {
                if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
                  wsRef.current.send(JSON.stringify({ type: 'video_frame', data: b64 }));
                }
              }}
              onRequestFixError={(details) => {
                handleSendCommand(`Fix the runtime exception in the game: ${details}`);
              }}
            />
          </div>

          {/* Draggable Horizontal Splitter: Workspace <-> Terminal */}
          <div
            onMouseDown={startResizeTerminal}
            style={{
              height: '4px',
              cursor: 'row-resize',
              backgroundColor: resizing === 'terminal' ? 'var(--accent-primary)' : 'var(--border-subtle)',
              transition: 'background-color 0.15s ease',
              zIndex: 10,
              flexShrink: 0,
            }}
            onMouseEnter={(e) => {
              if (!resizing) (e.currentTarget as HTMLElement).style.backgroundColor = 'var(--accent-primary)';
            }}
            onMouseLeave={(e) => {
              if (resizing !== 'terminal') (e.currentTarget as HTMLElement).style.backgroundColor = 'var(--border-subtle)';
            }}
          />

          {/* Bottom Dock: Activity Terminal */}
          <Terminal logs={logs} height={terminalHeight} onClearLogs={() => setLogs([])} />

          {/* Bottom Control Bar: Voice & Prompts */}
          <VoiceAndChatBar
            liveState={liveState}
            isMuted={isMuted}
            userTranscript={userTranscript}
            aiTranscript={aiTranscript}
            buildStage={buildStage}
            buildMessage={buildMessage}
            codeModels={codeModels}
            selectedCodeModel={selectedCodeModel}
            onToggleMute={handleToggleMute}
            onSendCommand={handleSendCommand}
            onSelectCodeModel={setSelectedCodeModel}
          />
        </div>
      )}

      {/* Settings & Onboarding Modal */}
      {settingsOpen && (
        <SettingsModal
          currentUser={currentUser}
          liveModels={liveModels}
          codeModels={codeModels}
          selectedLiveModel={selectedLiveModel}
          selectedCodeModel={selectedCodeModel}
          onSelectLiveModel={setSelectedLiveModel}
          onSelectCodeModel={setSelectedCodeModel}
          onClose={() => setSettingsOpen(false)}
          onShowToast={showToast}
        />
      )}

      {/* Non-blocking Toasts */}
      <ToastContainer toasts={toasts} onDismiss={(id) => setToasts((prev) => prev.filter((t) => t.id !== id))} />
    </div>
  );
};
