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
const DEFAULT_STARTER_HTML = `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
  <title>Neon Dodge</title>
  <link rel="stylesheet" href="style.css">
</head>
<body>
  <div id="game-container">
    <canvas id="gameCanvas"></canvas>
    <div id="hud">
      <div id="score">SCORE: 0</div>
      <div id="highScore">HIGH: 0</div>
    </div>
    <div id="gameOverScreen" class="overlay hidden">
      <h1>GAME OVER</h1>
      <p id="finalScore">Score: 0</p>
      <button id="restartBtn">Play Again</button>
    </div>
  </div>
  <script src="app.js"></script>
</body>
</html>`;

const DEFAULT_STARTER_CSS = `* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

body {
  background-color: #050110;
  color: #f0eef6;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  overflow: hidden;
  display: flex;
  justify-content: center;
  align-items: center;
  height: 100vh;
  width: 100vw;
  user-select: none;
}

#game-container {
  position: relative;
  width: 100%;
  height: 100%;
  display: flex;
  justify-content: center;
  align-items: center;
}

canvas {
  background: radial-gradient(circle at center, #11052c 0%, #050110 100%);
  display: block;
  box-shadow: 0 0 40px rgba(139, 92, 246, 0.2);
}

#hud {
  position: absolute;
  top: 16px;
  left: 20px;
  right: 20px;
  display: flex;
  justify-content: space-between;
  font-size: 14px;
  font-weight: 700;
  letter-spacing: 1px;
  font-family: monospace;
  pointer-events: none;
  z-index: 10;
  color: #38bdf8;
  text-shadow: 0 0 10px rgba(56, 189, 248, 0.6);
}

.overlay {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  background: rgba(5, 1, 16, 0.85);
  display: flex;
  flex-direction: column;
  justify-content: center;
  align-items: center;
  gap: 16px;
  z-index: 20;
  backdrop-filter: blur(8px);
}

.overlay.hidden {
  display: none !important;
}

.overlay h1 {
  font-size: 36px;
  font-weight: 800;
  color: #f43f5e;
  text-shadow: 0 0 20px rgba(244, 63, 94, 0.6);
}

.overlay p {
  font-size: 18px;
  color: #9590a8;
}

.overlay button {
  padding: 12px 28px;
  font-size: 14px;
  font-weight: 600;
  background: #8b5cf6;
  color: #ffffff;
  border: none;
  border-radius: 8px;
  cursor: pointer;
  box-shadow: 0 0 15px rgba(139, 92, 246, 0.4);
  transition: transform 0.15s ease, background 0.15s ease;
}

.overlay button:hover {
  background: #7c3aed;
  transform: translateY(-2px);
}`;

const DEFAULT_STARTER_JS = `// Neon Dodge - Sandboxed HTML5 Canvas Game
const canvas = document.getElementById('gameCanvas');
const ctx = canvas.getContext('2d');
const scoreEl = document.getElementById('score');
const highScoreEl = document.getElementById('highScore');
const gameOverScreen = document.getElementById('gameOverScreen');
const finalScoreEl = document.getElementById('finalScore');
const restartBtn = document.getElementById('restartBtn');

let width, height;
function resize() {
  width = canvas.width = window.innerWidth;
  height = canvas.height = window.innerHeight;
}
window.addEventListener('resize', resize);
resize();

// Player
const player = {
  x: width / 2,
  y: height / 2,
  radius: 12,
  speed: 6,
  vx: 0,
  vy: 0,
  color: '#38bdf8'
};

const keys = {};
window.addEventListener('keydown', e => { keys[e.code] = true; });
window.addEventListener('keyup', e => { keys[e.code] = false; });

// Particles & Enemies
let enemies = [];
let particles = [];
let score = 0;
let highScore = 0;
let gameOver = false;
let frameCount = 0;

function spawnEnemy() {
  const edge = Math.floor(Math.random() * 4);
  let x, y;
  if (edge === 0) { x = Math.random() * width; y = -20; }
  else if (edge === 1) { x = width + 20; y = Math.random() * height; }
  else if (edge === 2) { x = Math.random() * width; y = height + 20; }
  else { x = -20; y = Math.random() * height; }

  const angle = Math.atan2(player.y - y, player.x - x);
  const speed = 2 + Math.random() * 3 + Math.min(score / 500, 4);

  enemies.push({
    x, y,
    radius: 8 + Math.random() * 6,
    vx: Math.cos(angle) * speed,
    vy: Math.sin(angle) * speed,
    color: '#f43f5e'
  });
}

function createExplosion(x, y, color) {
  for (let i = 0; i < 20; i++) {
    const angle = Math.random() * Math.PI * 2;
    const speed = 1 + Math.random() * 4;
    particles.push({
      x, y,
      vx: Math.cos(angle) * speed,
      vy: Math.sin(angle) * speed,
      life: 30 + Math.random() * 20,
      maxLife: 50,
      color
    });
  }
}

function update() {
  if (gameOver) return;

  // Player movement
  player.vx = 0;
  player.vy = 0;
  if (keys['KeyW'] || keys['ArrowUp']) player.vy -= player.speed;
  if (keys['KeyS'] || keys['ArrowDown']) player.vy += player.speed;
  if (keys['KeyA'] || keys['ArrowLeft']) player.vx -= player.speed;
  if (keys['KeyD'] || keys['ArrowRight']) player.vx += player.speed;

  player.x += player.vx;
  player.y += player.vy;

  player.x = Math.max(player.radius, Math.min(width - player.radius, player.x));
  player.y = Math.max(player.radius, Math.min(height - player.radius, player.y));

  frameCount++;
  if (frameCount % Math.max(20, 60 - Math.floor(score / 100)) === 0) {
    spawnEnemy();
  }

  for (let i = enemies.length - 1; i >= 0; i--) {
    const e = enemies[i];
    e.x += e.vx;
    e.y += e.vy;

    const dist = Math.hypot(player.x - e.x, player.y - e.y);
    if (dist < player.radius + e.radius) {
      createExplosion(player.x, player.y, player.color);
      endGame();
      return;
    }

    if (e.x < -50 || e.x > width + 50 || e.y < -50 || e.y > height + 50) {
      enemies.splice(i, 1);
    }
  }

  for (let i = particles.length - 1; i >= 0; i--) {
    const p = particles[i];
    p.x += p.vx;
    p.y += p.vy;
    p.life--;
    if (p.life <= 0) particles.splice(i, 1);
  }

  score++;
  scoreEl.innerText = \`SCORE: \${score}\`;
  if (score > highScore) {
    highScore = score;
    highScoreEl.innerText = \`HIGH: \${highScore}\`;
  }
}

function render() {
  ctx.clearRect(0, 0, width, height);

  if (!gameOver) {
    ctx.shadowBlur = 15;
    ctx.shadowColor = player.color;
    ctx.fillStyle = player.color;
    ctx.beginPath();
    ctx.arc(player.x, player.y, player.radius, 0, Math.PI * 2);
    ctx.fill();
  }

  for (const e of enemies) {
    ctx.shadowBlur = 10;
    ctx.shadowColor = e.color;
    ctx.fillStyle = e.color;
    ctx.beginPath();
    ctx.arc(e.x, e.y, e.radius, 0, Math.PI * 2);
    ctx.fill();
  }

  for (const p of particles) {
    ctx.shadowBlur = 8;
    ctx.shadowColor = p.color;
    ctx.fillStyle = p.color;
    ctx.globalAlpha = p.life / p.maxLife;
    ctx.beginPath();
    ctx.arc(p.x, p.y, 2, 0, Math.PI * 2);
    ctx.fill();
  }
  ctx.globalAlpha = 1.0;
  ctx.shadowBlur = 0;
}

function loop() {
  update();
  render();
  requestAnimationFrame(loop);
}

function endGame() {
  gameOver = true;
  finalScoreEl.innerText = \`Score: \${score}\`;
  gameOverScreen.classList.remove('hidden');
}

function restartGame() {
  enemies = [];
  particles = [];
  score = 0;
  frameCount = 0;
  player.x = width / 2;
  player.y = height / 2;
  gameOver = false;
  gameOverScreen.classList.add('hidden');
}

restartBtn.addEventListener('click', restartGame);
loop();`;

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
        const demoProj: Project = {
          user_id: 0,
          username: 'demo',
          slug: 'neon-dodge',
          title: 'Neon Dodge',
          description: 'High-speed cyberpunk dodging arcade game',
          files: ['index.html', 'style.css', 'app.js'],
          tags: ['game', 'canvas', 'arcade'],
          is_public: true,
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        };
        setProjects([demoProj]);
        setCurrentProject(demoProj);
        setFiles({
          'index.html': DEFAULT_STARTER_HTML,
          'style.css': DEFAULT_STARTER_CSS,
          'app.js': DEFAULT_STARTER_JS,
        });
        setActiveFile('app.js');
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
              username={currentUser?.username || currentProject?.username || 'demo'}
              slug={currentProject?.slug || 'neon-dodge'}
              previewKey={previewKey}
              width={rightWidth}
              files={files}
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

      {/* Resizing mouse capture shield: prevents iframes from eating mousemove during splitter dragging */}
      {resizing && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            zIndex: 9999,
            cursor: resizing === 'terminal' ? 'row-resize' : 'col-resize',
          }}
        />
      )}

      {/* Non-blocking Toasts */}
      <ToastContainer toasts={toasts} onDismiss={(id) => setToasts((prev) => prev.filter((t) => t.id !== id))} />
    </div>
  );
};
