import os
import re
import io
import shutil
import zipfile
from pathlib import Path
import config

DANGEROUS_PATTERNS = [
    re.compile(r'parent\.document', re.IGNORECASE),
    re.compile(r'top\.document', re.IGNORECASE),
    re.compile(r'window\.opener', re.IGNORECASE),
    re.compile(r'window\.parent', re.IGNORECASE),
    re.compile(r'window\.top', re.IGNORECASE),
    re.compile(r'document\.cookie', re.IGNORECASE),
    re.compile(r'localStorage', re.IGNORECASE),
    re.compile(r'sessionStorage', re.IGNORECASE),
    re.compile(r'indexedDB', re.IGNORECASE),
    re.compile(r'XMLHttpRequest', re.IGNORECASE),
    re.compile(r'fetch\s*\(', re.IGNORECASE),
    re.compile(r'eval\s*\(', re.IGNORECASE),
    re.compile(r'Function\s*\(', re.IGNORECASE),
]

def sanitize_game_code(content: str) -> tuple[str, list[str]]:
    """
    Scans generated code for dangerous parent escape or storage sniffing patterns.
    Neutralizes direct escape vectors while preserving playable game logic.
    """
    warnings = []
    sanitized = content
    for pattern in DANGEROUS_PATTERNS:
        if pattern.search(sanitized):
            warnings.append(f"Neutralized risky pattern: {pattern.pattern}")
            sanitized = pattern.sub("/* blocked_security_rule */ null", sanitized)
    return sanitized, warnings

def get_user_project_dir(user_id: int, slug: str) -> Path:
    """
    Resolves project path and strictly verifies it stays within config.PROJECTS_DIR.
    Prevents path traversal attacks (Section 32).
    """
    if ".." in slug or "/" in slug or "\\" in slug:
        raise PermissionError("Path traversal attempt detected in slug.")
        
    safe_slug = re.sub(r'[^a-zA-Z0-9_-]', '', slug).lower()
    if not safe_slug:
        safe_slug = "game"
        
    base_root = config.PROJECTS_DIR.resolve()
    user_root = (base_root / str(int(user_id))).resolve()
    project_dir = (user_root / safe_slug).resolve()
    
    # Strict containment check
    try:
        project_dir.relative_to(user_root)
    except ValueError:
        raise PermissionError("Path traversal attempt detected.")
        
    project_dir.mkdir(parents=True, exist_ok=True)
    return project_dir

def get_project_size(project_dir: Path) -> int:
    """Calculates total size of all files inside a project directory."""
    total = 0
    if not project_dir.exists():
        return 0
    for p in project_dir.rglob("*"):
        if p.is_file():
            total += p.stat().st_size
    return total

def write_project_file(user_id: int, slug: str, filename: str, content: str) -> str:
    """
    Writes a project file enforcing size limits and path sanitization.
    """
    if ".." in filename or "/" in filename or "\\" in filename:
        raise PermissionError("Path traversal attempt detected in filename.")
        
    # Sanitize file name
    safe_name = os.path.basename(filename).strip()
    if not re.match(r'^[a-zA-Z0-9_.\-]+$', safe_name) or '..' in safe_name:
        raise ValueError(f"Invalid filename: {filename}")
        
    # File size check (Section 31: 512 KB per file)
    encoded = content.encode("utf-8")
    if len(encoded) > config.MAX_FILE_SIZE:
        raise ValueError(f"File {safe_name} exceeds the maximum allowed file size of 512 KB.")
        
    pdir = get_user_project_dir(user_id, slug)
    target = (pdir / safe_name).resolve()
    
    # Traversal check
    if not str(target).startswith(str(pdir)):
        raise PermissionError("Path traversal detected in filename.")
        
    # Security check against dangerous parent escape patterns
    if safe_name.endswith((".html", ".js")):
        clean_content, warnings = sanitize_game_code(content)
        encoded = clean_content.encode("utf-8")
        
    # Project total size check (Section 31: 2 MB total project size)
    current_size = get_project_size(pdir)
    target_existing_size = target.stat().st_size if target.exists() else 0
    new_total_size = current_size - target_existing_size + len(encoded)
    if new_total_size > config.MAX_PROJECT_SIZE:
        raise ValueError("Project total size exceeds the maximum allowed limit of 2 MB.")
        
    target.write_bytes(encoded)
    return safe_name

def read_project_file(user_id: int, slug: str, filename: str) -> str:
    safe_name = os.path.basename(filename)
    pdir = get_user_project_dir(user_id, slug)
    target = (pdir / safe_name).resolve()
    if not str(target).startswith(str(pdir)) or not target.exists():
        return ""
    return target.read_text(encoding="utf-8", errors="replace")

def list_project_files(user_id: int, slug: str) -> list:
    pdir = get_user_project_dir(user_id, slug)
    if not pdir.exists():
        return []
    files = []
    for item in pdir.iterdir():
        if item.is_file():
            files.append(item.name)
    return sorted(files)

def get_project_all_files(user_id: int, slug: str) -> dict:
    """Returns a dictionary of all standard files and their content."""
    files = {}
    for fname in ["index.html", "style.css", "app.js"]:
        files[fname] = read_project_file(user_id, slug, fname)
    return files

def create_starter_game(user_id: int, username: str, slug: str, title: str):
    """
    Generates a clean, playable Neon Dodge starter game.
    Follows Yulya Studio design system tokens and HTML5 Canvas best practices.
    """
    pdir = get_user_project_dir(user_id, slug)
    
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title}</title>
  <link rel="stylesheet" href="style.css">
</head>
<body>
  <div class="game-shell">
    <div class="hud">
      <div class="brand">
        <span class="dot"></span>
        <span class="game-title">{title}</span>
      </div>
      <div class="stats">
        <div class="stat-item">SCORE <span id="scoreVal">0</span></div>
        <div class="stat-item">BEST <span id="bestVal">0</span></div>
      </div>
    </div>
    <div class="canvas-wrap">
      <canvas id="gameCanvas" width="600" height="400"></canvas>
      <div id="overlay" class="overlay">
        <h2 id="overlayTitle">NEON DODGE</h2>
        <p id="overlaySub">Dodge incoming red sparks with Arrow Keys or WASD</p>
        <button id="startBtn" class="play-btn">START GAME</button>
      </div>
    </div>
    <div class="footer-note">
      Created by @{username} &bull; Powered by Yulya Studio
    </div>
  </div>
  <script src="app.js"></script>
</body>
</html>
"""

    css = """* {
  box-sizing: border-box;
  margin: 0;
  padding: 0;
}

:root {
  --bg: #050110;
  --panel: #0a0518;
  --accent: #8b5cf6;
  --cyan: #38bdf8;
  --rose: #f43f5e;
  --green: #34d399;
  --text: #f0eef6;
  --muted: #9590a8;
}

body {
  background: var(--bg);
  color: var(--text);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  display: flex;
  justify-content: center;
  align-items: center;
  min-height: 100vh;
  overflow: hidden;
  user-select: none;
}

.game-shell {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  background: var(--panel);
  border: 1px solid rgba(120, 80, 160, 0.2);
  border-radius: 14px;
  padding: 16px;
  box-shadow: 0 10px 40px rgba(0, 0, 0, 0.6);
  max-width: 640px;
  width: 100%;
}

.hud {
  display: flex;
  justify-content: space-between;
  align-items: center;
  width: 100%;
  padding: 4px 8px;
}

.brand {
  display: flex;
  align-items: center;
  gap: 8px;
}

.brand .dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--green);
  box-shadow: 0 0 8px var(--green);
}

.game-title {
  font-size: 0.95rem;
  font-weight: 700;
  letter-spacing: 0.5px;
  color: var(--text);
}

.stats {
  display: flex;
  gap: 16px;
  font-family: monospace;
  font-size: 0.85rem;
  color: var(--muted);
}

.stat-item span {
  color: var(--cyan);
  font-weight: 700;
  margin-left: 4px;
}

.canvas-wrap {
  position: relative;
  width: 600px;
  height: 400px;
  border-radius: 8px;
  overflow: hidden;
  border: 1px solid rgba(120, 80, 160, 0.3);
  background: #000;
}

canvas {
  display: block;
  width: 100%;
  height: 100%;
  background: #070314;
}

.overlay {
  position: absolute;
  inset: 0;
  background: rgba(5, 1, 16, 0.88);
  display: flex;
  flex-direction: column;
  justify-content: center;
  align-items: center;
  gap: 12px;
  backdrop-filter: blur(4px);
  transition: opacity 0.2s ease;
}

.overlay.hidden {
  opacity: 0;
  pointer-events: none;
}

.overlay h2 {
  font-size: 1.8rem;
  font-weight: 800;
  color: #fff;
  letter-spacing: 1px;
}

.overlay p {
  font-size: 0.9rem;
  color: var(--muted);
  max-width: 320px;
  text-align: center;
  line-height: 1.4;
}

.play-btn {
  margin-top: 8px;
  background: var(--accent);
  color: #fff;
  border: none;
  border-radius: 8px;
  padding: 10px 24px;
  font-size: 0.9rem;
  font-weight: 700;
  cursor: pointer;
  transition: all 0.15s ease;
}

.play-btn:hover {
  background: #9d74f7;
  transform: translateY(-1px);
}

.footer-note {
  font-size: 0.75rem;
  color: var(--muted);
  text-align: center;
}
"""

    js = """// Neon Dodge — Starter Game
const canvas = document.getElementById('gameCanvas');
const ctx = canvas.getContext('2d');
const scoreEl = document.getElementById('scoreVal');
const bestEl = document.getElementById('bestVal');
const overlay = document.getElementById('overlay');
const overlayTitle = document.getElementById('overlayTitle');
const overlaySub = document.getElementById('overlaySub');
const startBtn = document.getElementById('startBtn');

let score = 0;
let highScore = 0;
let isPlaying = false;
let animId = null;

const player = {
  x: canvas.width / 2,
  y: canvas.height - 50,
  size: 20,
  speed: 6,
  color: '#38bdf8'
};

let enemies = [];
let particles = [];
let keys = {};
let spawnTimer = 0;

window.addEventListener('keydown', (e) => {
  keys[e.key.toLowerCase()] = true;
});

window.addEventListener('keyup', (e) => {
  keys[e.key.toLowerCase()] = false;
});

// Touch / pointer support for mobile
let touchActive = false;
canvas.addEventListener('pointerdown', (e) => {
  touchActive = true;
  movePlayerToPointer(e);
});
canvas.addEventListener('pointermove', (e) => {
  if (touchActive) movePlayerToPointer(e);
});
window.addEventListener('pointerup', () => touchActive = false);

function movePlayerToPointer(e) {
  const rect = canvas.getBoundingClientRect();
  const scaleX = canvas.width / rect.width;
  player.x = (e.clientX - rect.left) * scaleX - player.size / 2;
  clampPlayer();
}

function clampPlayer() {
  player.x = Math.max(0, Math.min(canvas.width - player.size, player.x));
  player.y = Math.max(0, Math.min(canvas.height - player.size, player.y));
}

function spawnEnemy() {
  const size = Math.random() * 16 + 12;
  enemies.push({
    x: Math.random() * (canvas.width - size),
    y: -size,
    size: size,
    speed: Math.random() * 3.5 + 2.5,
    color: '#f43f5e'
  });
}

function createExplosion(x, y, color) {
  for (let i = 0; i < 18; i++) {
    const angle = Math.random() * Math.PI * 2;
    const speed = Math.random() * 4 + 1;
    particles.push({
      x: x,
      y: y,
      vx: Math.cos(angle) * speed,
      vy: Math.sin(angle) * speed,
      alpha: 1,
      color: color
    });
  }
}

function startGame() {
  score = 0;
  scoreEl.textContent = '0';
  enemies = [];
  particles = [];
  player.x = canvas.width / 2 - player.size / 2;
  player.y = canvas.height - 50;
  isPlaying = true;
  overlay.classList.add('hidden');
  lastTime = performance.now();
  if (animId) cancelAnimationFrame(animId);
  loop();
}

function gameOver() {
  isPlaying = false;
  createExplosion(player.x + player.size / 2, player.y + player.size / 2, player.color);
  if (score > highScore) {
    highScore = score;
    bestEl.textContent = highScore;
  }
  overlayTitle.textContent = 'GAME OVER';
  overlaySub.textContent = `You scored ${score} points! Press the button to play again.`;
  startBtn.textContent = 'PLAY AGAIN';
  overlay.classList.remove('hidden');
}

let lastTime = 0;

function loop(time = 0) {
  if (!isPlaying) return;
  animId = requestAnimationFrame(loop);

  // Movement
  if (keys['arrowleft'] || keys['a']) player.x -= player.speed;
  if (keys['arrowright'] || keys['d']) player.x += player.speed;
  if (keys['arrowup'] || keys['w']) player.y -= player.speed;
  if (keys['arrowdown'] || keys['s']) player.y += player.speed;
  clampPlayer();

  // Enemy Spawning
  spawnTimer++;
  const spawnRate = Math.max(20, 45 - Math.floor(score / 50));
  if (spawnTimer % spawnRate === 0) {
    spawnEnemy();
  }

  // Update & Collision
  for (let i = enemies.length - 1; i >= 0; i--) {
    const e = enemies[i];
    e.y += e.speed;

    // AABB collision
    if (
      player.x < e.x + e.size &&
      player.x + player.size > e.x &&
      player.y < e.y + e.size &&
      player.y + player.size > e.y
    ) {
      gameOver();
      return;
    }

    // Pass bottom
    if (e.y > canvas.height + 20) {
      enemies.splice(i, 1);
      score += 10;
      scoreEl.textContent = score;
    }
  }

  // Particles
  for (let i = particles.length - 1; i >= 0; i--) {
    const p = particles[i];
    p.x += p.vx;
    p.y += p.vy;
    p.alpha -= 0.03;
    if (p.alpha <= 0) particles.splice(i, 1);
  }

  // Render
  ctx.clearRect(0, 0, canvas.width, canvas.height);

  // Subtle grid
  ctx.strokeStyle = 'rgba(120, 80, 160, 0.08)';
  ctx.lineWidth = 1;
  const gridSize = 40;
  for (let x = 0; x < canvas.width; x += gridSize) {
    ctx.beginPath();
    ctx.moveTo(x, 0);
    ctx.lineTo(x, canvas.height);
    ctx.stroke();
  }
  for (let y = 0; y < canvas.height; y += gridSize) {
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(canvas.width, y);
    ctx.stroke();
  }

  // Player
  ctx.shadowColor = player.color;
  ctx.shadowBlur = 12;
  ctx.fillStyle = player.color;
  ctx.fillRect(player.x, player.y, player.size, player.size);

  // Enemies
  for (const e of enemies) {
    ctx.shadowColor = e.color;
    ctx.shadowBlur = 10;
    ctx.fillStyle = e.color;
    ctx.beginPath();
    ctx.arc(e.x + e.size / 2, e.y + e.size / 2, e.size / 2, 0, Math.PI * 2);
    ctx.fill();
  }

  // Particles
  ctx.shadowBlur = 0;
  for (const p of particles) {
    ctx.fillStyle = p.color;
    ctx.globalAlpha = Math.max(0, p.alpha);
    ctx.fillRect(p.x, p.y, 3, 3);
  }
  ctx.globalAlpha = 1.0;
}

startBtn.addEventListener('click', startGame);
"""

    (pdir / "index.html").write_text(html, encoding="utf-8")
    (pdir / "style.css").write_text(css, encoding="utf-8")
    (pdir / "app.js").write_text(js, encoding="utf-8")
    return ["index.html", "style.css", "app.js"]

def delete_project_dir(user_id: int, slug: str) -> bool:
    safe_slug = re.sub(r'[^a-zA-Z0-9_-]', '', slug).lower()
    pdir = config.PROJECTS_DIR / str(int(user_id)) / safe_slug
    if pdir.exists() and str(pdir.resolve()).startswith(str(config.PROJECTS_DIR.resolve())):
        shutil.rmtree(pdir, ignore_errors=True)
        return True
    return False

def create_zip_archive(user_id: int, slug: str) -> io.BytesIO:
    pdir = get_user_project_dir(user_id, slug)
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for file_path in pdir.rglob("*"):
            if file_path.is_file():
                arcname = file_path.relative_to(pdir)
                zf.write(file_path, arcname)
    zip_buffer.seek(0)
    return zip_buffer
