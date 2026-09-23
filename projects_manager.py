import os
import re
import io
import json
import shutil
import zipfile
from pathlib import Path
from datetime import datetime, timezone
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

PROTECTED_FILES = {
    "profile.json", "user.json", "build.log", "database.py", "server.py",
    "config.py", "ai_engine.py", "projects_manager.py", "test_suite.py", "requirements.txt"
}

DISALLOWED_EXTENSIONS = {
    ".py", ".pyc", ".sh", ".bash", ".bat", ".cmd", ".ps1", ".exe", ".env", ".dll", ".so", ".bin"
}

ALLOWED_GAME_EXTENSIONS = {
    ".html", ".css", ".js", ".json", ".svg", ".txt", ".csv", ".tsv", ".xml",
    ".png", ".jpg", ".jpeg", ".webp", ".mp3", ".wav", ".ogg",
    ".obj", ".gltf", ".glb", ".dae"
}

def get_user_project_dir(user_id: int, slug: str) -> Path:
    """
    Resolves project path and strictly verifies it stays within config.PROJECTS_DIR/{user_id}/{slug}.
    Prevents path traversal attacks, directory escaping, and cross-project tampering.
    """
    try:
        user_id_int = int(user_id)
        if user_id_int <= 0:
            raise PermissionError("Invalid user ID: must be a positive integer.")
    except (ValueError, TypeError):
        raise PermissionError("Invalid user ID format.")

    if not slug or not isinstance(slug, str):
        raise PermissionError("Project slug is required.")
        
    # Strictly reject path traversal patterns
    if any(p in slug for p in ["..", "/", "\\", "%", "\0", ":"]):
        raise PermissionError("Path traversal attempt detected in slug.")
        
    safe_slug = re.sub(r'[^a-zA-Z0-9_-]', '', slug).lower()
    if not safe_slug:
        raise PermissionError("Invalid project slug: empty after sanitization.")

    if safe_slug.upper() in {"CON", "PRN", "AUX", "NUL", "COM1", "COM2", "COM3", "COM4", "LPT1", "LPT2"}:
        raise PermissionError(f"Reserved device name in slug: {safe_slug}")
        
    base_root = config.PROJECTS_DIR.resolve()
    user_root = (base_root / str(user_id_int)).resolve()
    project_dir = (user_root / safe_slug).resolve()
    
    # Strict containment check - must be strictly inside user_root and base_root
    try:
        project_dir.relative_to(user_root)
        project_dir.relative_to(base_root)
    except ValueError:
        raise PermissionError("Path traversal attempt detected: path escapes project repository.")
        
    if project_dir == user_root or project_dir == base_root:
        raise PermissionError("Cannot access root directory.")
        
    return project_dir

def get_project_size(project_dir: Path) -> int:
    """Calculates total size of all files inside a project directory."""
    total = 0
    if not project_dir.exists():
        return 0
    for p in project_dir.rglob("*"):
        if p.is_file() and not p.is_symlink():
            total += p.stat().st_size
    return total

def write_project_file(user_id: int, slug: str, filename: str, content: str) -> str:
    """
    Writes a project file enforcing strict path isolation, size limits, and security rules.
    Supports subfolders (e.g. js/engine.js, assets/sprite.svg) while guaranteeing that
    files cannot escape data/projects/{user_id}/{slug}/ or touch profiles/server files.
    """
    if not filename or not isinstance(filename, str):
        raise ValueError("Filename is required.")
        
    clean_path = filename.replace("\\", "/").strip().lstrip("/")
    if not clean_path:
        raise ValueError("Filename is required.")
        
    if any(p in clean_path for p in ["..", "%", "\0", ":"]):
        raise PermissionError("Path traversal attempt detected in filename.")
        
    parts = clean_path.split("/")
    if any(p in ("..", ".", "") or not re.match(r'^[a-zA-Z0-9_.\-]+$', p) for p in parts):
        raise PermissionError("Path traversal attempt detected: invalid path components.")
        
    safe_name = parts[-1]
    # Block protected or system files
    if safe_name.startswith(".") or safe_name in PROTECTED_FILES or any(p in PROTECTED_FILES for p in parts):
        raise PermissionError(f"Access denied: cannot modify protected file '{clean_path}'.")

    # Block disallowed extensions
    ext = Path(safe_name).suffix.lower()
    if ext in DISALLOWED_EXTENSIONS or ext not in ALLOWED_GAME_EXTENSIONS:
        raise PermissionError(f"Access denied: file '{clean_path}' has disallowed extension.")
        
    # File size check
    encoded = content.encode("utf-8") if isinstance(content, str) else content
    if len(encoded) > config.MAX_FILE_SIZE:
        raise ValueError(f"File {clean_path} exceeds the maximum allowed file size.")
        
    pdir = get_user_project_dir(user_id, slug).resolve()
    target = (pdir / clean_path).resolve()
    
    # Traversal and symlink check
    try:
        target.relative_to(pdir)
    except ValueError:
        raise PermissionError("Path traversal detected: target is outside project directory.")
        
    if target.is_symlink() or os.path.islink(str(target)):
        raise PermissionError("Symlinks are strictly forbidden.")
        
    # Security check against dangerous parent escape patterns
    if safe_name.endswith((".html", ".js")):
        clean_content, warnings = sanitize_game_code(content if isinstance(content, str) else content.decode("utf-8", errors="replace"))
        encoded = clean_content.encode("utf-8")
        
    # Project total size check
    current_size = get_project_size(pdir)
    target_existing_size = target.stat().st_size if target.exists() else 0
    new_total_size = current_size - target_existing_size + len(encoded)
    if new_total_size > config.MAX_PROJECT_SIZE:
        raise ValueError("Project total size exceeds the maximum allowed limit.")
        
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(encoded)
    return clean_path

def read_project_file(user_id: int, slug: str, filename: str) -> str:
    """
    Reads a file strictly from within the game project repository.
    Supports relative subpaths and rejects any traversal, symlink, or outside read.
    """
    if not filename or not isinstance(filename, str):
        return ""
        
    clean_path = filename.replace("\\", "/").strip().lstrip("/")
    if not clean_path or any(p in clean_path for p in ["..", "%", "\0", ":"]):
        raise PermissionError("Path traversal attempt detected in filename.")
        
    parts = clean_path.split("/")
    if any(p in ("..", ".", "") or not re.match(r'^[a-zA-Z0-9_.\-]+$', p) for p in parts):
        raise PermissionError("Invalid filename: invalid path components.")
        
    safe_name = parts[-1]
    if safe_name in PROTECTED_FILES or safe_name.startswith(".") or any(p in PROTECTED_FILES for p in parts):
        raise PermissionError(f"Access denied: cannot read protected file '{clean_path}'.")

    ext = Path(safe_name).suffix.lower()
    if ext in DISALLOWED_EXTENSIONS:
        raise PermissionError(f"Access denied: cannot read file with disallowed extension '{clean_path}'.")

    pdir = get_user_project_dir(user_id, slug).resolve()
    target = (pdir / clean_path).resolve()
    
    try:
        target.relative_to(pdir)
    except ValueError:
        raise PermissionError("Path traversal detected in filename.")
        
    if target.is_symlink() or os.path.islink(str(target)):
        raise PermissionError("Symlinks are strictly forbidden.")
        
    if not target.exists() or not target.is_file():
        return ""
    return target.read_text(encoding="utf-8", errors="replace")

def list_project_files(user_id: int, slug: str) -> list:
    """Lists only valid game code files within the project repository recursively."""
    pdir = get_user_project_dir(user_id, slug).resolve()
    if not pdir.exists():
        return []
    files = []
    for item in pdir.rglob("*"):
        if item.is_file() and not item.is_symlink():
            try:
                rel_path = item.resolve().relative_to(pdir).as_posix()
                parts = rel_path.split("/")
                if any(p.startswith(".") or p in PROTECTED_FILES for p in parts) or "build.log" in parts:
                    continue
                ext = item.suffix.lower()
                if ext in DISALLOWED_EXTENSIONS or ext not in ALLOWED_GAME_EXTENSIONS:
                    continue
                files.append(rel_path)
            except ValueError:
                continue
    return sorted(files)

def get_project_all_files(user_id: int, slug: str) -> dict:
    """Returns a dictionary of all game files within the repository."""
    files = {}
    valid_files = set(list_project_files(user_id, slug))
    for std_f in ["index.html", "style.css", "app.js"]:
        valid_files.add(std_f)
    for fname in sorted(valid_files):
        try:
            content = read_project_file(user_id, slug, fname)
            if content or fname in ["index.html", "style.css", "app.js"]:
                files[fname] = content
        except Exception:
            pass
    return files

# --- Antigravity CLI Activity Log & Persistence (Section 4) ---

def write_build_log(user_id: int, slug: str, step: str, message: str) -> None:
    """
    Persists an Antigravity CLI activity log entry into data/projects/{user_id}/{slug}/build.log
    Steps: USER, THINKING, READ_FILE, REPLACE_CONTENT, PASS, FAIL
    """
    pdir = get_user_project_dir(user_id, slug).resolve()
    log_file = (pdir / "build.log").resolve()
    try:
        log_file.relative_to(pdir)
    except ValueError:
        raise PermissionError("Invalid path for build log.")
        
    pdir.mkdir(parents=True, exist_ok=True)
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    formatted_line = f"[{now_str}] [{step.upper()}] {message}\n"
    with open(log_file, "a", encoding="utf-8", errors="replace") as f:
        f.write(formatted_line)

def read_build_log(user_id: int, slug: str, max_lines: int = 100) -> list[dict]:
    """
    Reads recent activity log entries from build.log for the studio terminal feed.
    """
    pdir = get_user_project_dir(user_id, slug).resolve()
    log_file = (pdir / "build.log").resolve()
    if not log_file.exists():
        return []
        
    try:
        log_file.relative_to(pdir)
    except ValueError:
        return []
        
    try:
        lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
        recent = lines[-max_lines:]
        parsed = []
        for line in recent:
            # Parse line format: [2026-09-20 22:00:00] [STEP] Message
            match = re.match(r'^\[(.*?)\]\s+\[(.*?)\]\s+(.*)$', line)
            if match:
                parsed.append({
                    "time": match.group(1).split(" ")[-1],
                    "step": match.group(2).lower(),
                    "message": match.group(3)
                })
            else:
                parsed.append({
                    "time": "",
                    "step": "info",
                    "message": line
                })
        return parsed
    except Exception:
        return []

def create_starter_game(user_id: int, username: str, slug: str, title: str):
    """
    Generates a clean, playable Neon Dodge starter game.
    Follows Yulya Studio design system tokens and HTML5 Canvas best practices.
    HTML-escapes title and username to prevent XSS / markup injection.
    """
    import html as html_lib
    pdir = get_user_project_dir(user_id, slug)
    safe_title = html_lib.escape(title[:80]) if title else "Neon Dodge"
    safe_username = html_lib.escape(username[:40]) if username else "creator"
    
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{safe_title}</title>
  <link rel="stylesheet" href="style.css">
</head>
<body>
  <div class="game-shell">
    <div class="hud">
      <div class="brand">
        <span class="dot"></span>
        <span class="game-title">{safe_title}</span>
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
      Created by @{safe_username} &bull; Powered by Yulya Studio
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

    pdir.mkdir(parents=True, exist_ok=True)
    write_project_file(user_id, slug, "index.html", html)
    write_project_file(user_id, slug, "style.css", css)
    write_project_file(user_id, slug, "app.js", js)
    
    # Initialize starter project manifest for architectural memory
    initial_manifest = {
        "title": title,
        "slug": slug.lower(),
        "engine": "canvas2d",
        "architecture": "starter-loop",
        "files": ["index.html", "style.css", "app.js"],
        "systems": ["movement", "enemy_spawner", "collision_aabb", "scoring", "particle_effects"],
        "controls": ["keyboard_arrows_wasd", "touch_pointer"],
        "known_bugs": [],
        "design_decisions": ["cyberpunk_neon_theme", "particle_explosions", "adaptive_difficulty"],
        "creator_preferences": [],
        "performance_targets": {"fps": 60, "resolution": "600x400"},
        "current_build": 1,
        "updated_at": datetime.now(timezone.utc).isoformat()
    }
    (pdir / "project_manifest.json").write_text(json.dumps(initial_manifest, indent=2), encoding="utf-8")
    return ["index.html", "style.css", "app.js"]

def delete_project_file(user_id: int, slug: str, filename: str) -> bool:
    """
    Safely deletes a file from the project repository.
    Enforces path containment, blocks deletion of PROTECTED_FILES and hidden files.
    """
    if not filename or not isinstance(filename, str):
        return False
        
    clean_name = filename.replace("\\", "/").strip().lstrip("/")
    if any(p in clean_name for p in ["..", "%", "\0", ":"]):
        raise PermissionError("Path traversal attempt in filename.")
        
    parts = clean_name.split("/")
    for part in parts:
        if not re.match(r'^[a-zA-Z0-9_.\-]+$', part) or part in {".", ".."}:
            raise ValueError(f"Invalid filename component: {part}")
            
    safe_name = parts[-1]
    if safe_name.startswith(".") or safe_name in PROTECTED_FILES or any(p in PROTECTED_FILES for p in parts):
        raise PermissionError(f"Cannot delete protected file: {safe_name}")
        
    pdir = get_user_project_dir(user_id, slug)
    target = (pdir / clean_name).resolve()
    
    try:
        target.relative_to(pdir)
    except ValueError:
        raise PermissionError("Path traversal attempt: file outside project repository.")
        
    if target.is_symlink() or os.path.islink(target):
        raise PermissionError("Symlinks are not allowed.")
        
    if target.exists() and target.is_file():
        target.unlink()
        curr = target.parent
        while curr != pdir and curr.exists() and not any(curr.iterdir()):
            try:
                curr.rmdir()
                curr = curr.parent
            except Exception:
                break
        return True
    return False

def search_project_files(user_id: int, slug: str, query: str, max_results: int = 20) -> list[dict]:
    """
    Searches across text files in the project for a query substring (case-insensitive).
    Returns list of matches: [{"file": relative_path, "line": line_no, "snippet": text}]
    """
    if not query or not isinstance(query, str):
        return []
        
    pdir = get_user_project_dir(user_id, slug)
    if not pdir.exists():
        return []
        
    files = list_project_files(user_id, slug)
    results = []
    lower_query = query.lower()
    text_extensions = {".html", ".css", ".js", ".json", ".svg", ".txt", ".csv", ".tsv", ".xml"}
    
    for frel in files:
        target = (pdir / frel).resolve()
        if not target.exists() or not target.is_file() or target.suffix.lower() not in text_extensions:
            continue
        try:
            content = target.read_text(encoding="utf-8", errors="replace")
            for line_no, line in enumerate(content.splitlines(), start=1):
                if lower_query in line.lower():
                    results.append({
                        "file": frel,
                        "line": line_no,
                        "snippet": line.strip()[:150]
                    })
                    if len(results) >= max_results:
                        return results
        except Exception:
            continue
            
    return results

def get_project_tree(user_id: int, slug: str) -> dict:
    """
    Builds a tree structure of all files and folders in the project repository.
    """
    pdir = get_user_project_dir(user_id, slug)
    if not pdir.exists():
        return {"name": slug, "type": "directory", "children": []}
        
    def _build_node(path: Path) -> dict:
        if path.is_dir():
            children = []
            for child in sorted(path.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
                if child.name.startswith(".") or child.name in PROTECTED_FILES or child.name == "build.log":
                    continue
                if child.is_symlink() or os.path.islink(child):
                    continue
                children.append(_build_node(child))
            return {
                "name": path.name,
                "type": "directory",
                "children": children
            }
        else:
            return {
                "name": path.name,
                "type": "file",
                "size": path.stat().st_size if path.exists() else 0,
                "ext": path.suffix.lower()
            }
            
    root_node = _build_node(pdir)
    root_node["name"] = slug
    return root_node

def get_project_manifest(user_id: int, slug: str) -> dict:
    """
    Reads the project_manifest.json file. If missing, auto-generates one from current files.
    """
    manifest_raw = read_project_file(user_id, slug, "project_manifest.json")
    if manifest_raw:
        try:
            return json.loads(manifest_raw)
        except Exception:
            pass
            
    files = list_project_files(user_id, slug)
    html_content = read_project_file(user_id, slug, "index.html")
    
    engine = "canvas2d"
    libraries = []
    html_lower = html_content.lower() if html_content else ""
    if "phaser" in html_lower:
        engine = "phaser"
        libraries.append("Phaser")
    elif "three" in html_lower:
        engine = "three.js"
        libraries.append("Three.js")
    elif "pixi" in html_lower:
        engine = "pixijs"
        libraries.append("PixiJS")
    elif "matter" in html_lower:
        engine = "matter.js"
        libraries.append("Matter.js")
        
    baseline = {
        "slug": slug,
        "engine": engine,
        "libraries": libraries,
        "architecture": "modular" if len(files) > 3 else "starter-loop",
        "files": files,
        "systems": ["rendering", "game_loop", "input_handling"],
        "controls": ["keyboard", "pointer"],
        "known_bugs": [],
        "design_decisions": [],
        "creator_preferences": [],
        "performance_targets": {"fps": 60, "resolution": "responsive"},
        "current_build": 1,
        "updated_at": datetime.now(timezone.utc).isoformat()
    }
    return baseline

def update_project_manifest(user_id: int, slug: str, updates: dict) -> dict:
    """
    Merges updates into project_manifest.json and saves to disk.
    """
    manifest = get_project_manifest(user_id, slug)
    for k, v in updates.items():
        if k in ["known_bugs", "design_decisions", "creator_preferences", "systems", "controls", "libraries"]:
            if isinstance(v, list):
                existing_list = manifest.get(k, [])
                for item in v:
                    if item not in existing_list:
                        existing_list.append(item)
                manifest[k] = existing_list
            elif isinstance(v, str):
                existing_list = manifest.get(k, [])
                if v not in existing_list:
                    existing_list.append(v)
                manifest[k] = existing_list
        else:
            manifest[k] = v
            
    manifest["files"] = list_project_files(user_id, slug)
    manifest["updated_at"] = datetime.now(timezone.utc).isoformat()
    
    write_project_file(user_id, slug, "project_manifest.json", json.dumps(manifest, indent=2))
    return manifest

def validate_project(user_id: int, slug: str) -> dict:
    """
    Validates project structure, integrity, references, and security.
    Returns diagnostic report: { "valid": bool, "errors": [...], "warnings": [...], ... }
    """
    errors = []
    warnings = []
    files = list_project_files(user_id, slug)
    
    if "index.html" not in files:
        errors.append("Critical: 'index.html' is missing from the project root.")
        
    html_content = read_project_file(user_id, slug, "index.html") if "index.html" in files else ""
    detected_engine = "canvas2d"
    detected_libs = []
    
    if html_content:
        if "<!DOCTYPE" not in html_content and "<!doctype" not in html_content:
            warnings.append("Missing <!DOCTYPE html> declaration in index.html.")
            
        script_srcs = re.findall(r'<script\s+[^>]*src=["\']([^"\']+)["\']', html_content, re.IGNORECASE)
        for src in script_srcs:
            if src.startswith("http://") or src.startswith("https://") or src.startswith("//"):
                src_lower = src.lower()
                if "phaser" in src_lower:
                    detected_engine = "phaser"
                    detected_libs.append("Phaser")
                elif "three" in src_lower:
                    detected_engine = "three.js"
                    detected_libs.append("Three.js")
                elif "pixi" in src_lower:
                    detected_engine = "pixijs"
                    detected_libs.append("PixiJS")
                elif "matter" in src_lower:
                    detected_libs.append("Matter.js")
                elif "howler" in src_lower:
                    detected_libs.append("Howler.js")
            else:
                clean_ref = src.split("?")[0].lstrip("/")
                if clean_ref not in files:
                    errors.append(f"Broken script reference in index.html: '{src}' does not exist.")
                    
        link_hrefs = re.findall(r'<link\s+[^>]*href=["\']([^"\']+)["\']', html_content, re.IGNORECASE)
        for href in link_hrefs:
            if not (href.startswith("http://") or href.startswith("https://") or href.startswith("//")):
                clean_ref = href.split("?")[0].lstrip("/")
                if clean_ref not in files and not href.endswith(".ico"):
                    errors.append(f"Broken stylesheet reference in index.html: '{href}' does not exist.")
                    
        if "<canvas" not in html_content.lower() and detected_engine == "canvas2d":
            warnings.append("No <canvas> element found in index.html for Canvas 2D game.")
            
    for f in files:
        if f.endswith(".js"):
            js_code = read_project_file(user_id, slug, f)
            open_curly = js_code.count("{")
            close_curly = js_code.count("}")
            if open_curly != close_curly:
                warnings.append(f"Potential syntax warning in '{f}': unbalanced curly braces ({open_curly} open vs {close_curly} close).")
                
            open_paren = js_code.count("(")
            close_paren = js_code.count(")")
            if open_paren != close_paren:
                warnings.append(f"Potential syntax warning in '{f}': unbalanced parentheses ({open_paren} open vs {close_paren} close).")
                
            for pattern in DANGEROUS_PATTERNS:
                if pattern.search(js_code):
                    warnings.append(f"Security flag in '{f}': pattern '{pattern.pattern}' detected.")
                    
            if re.search(r'while\s*\(\s*true\s*\)\s*\{(?:(?!break).)*\}', js_code, re.DOTALL):
                warnings.append(f"Performance warning in '{f}': potential unbounded while(true) loop detected.")
                
    pdir = get_user_project_dir(user_id, slug)
    total_size = get_project_size(pdir)
    
    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "files_checked": files,
        "detected_engine": detected_engine,
        "libraries": list(set(detected_libs)),
        "stats": {
            "total_files": len(files),
            "total_size_bytes": total_size
        }
    }

def delete_project_dir(user_id: int, slug: str) -> bool:
    try:
        user_id_int = int(user_id)
        if user_id_int <= 0:
            return False
    except (ValueError, TypeError):
        return False

    if not slug or any(p in slug for p in ["..", "/", "\\", "%", "\0", ":"]):
        return False
    safe_slug = re.sub(r'[^a-zA-Z0-9_-]', '', slug).lower()
    if not safe_slug:
        return False
    base_root = config.PROJECTS_DIR.resolve()
    user_root = (base_root / str(user_id_int)).resolve()
    pdir = (user_root / safe_slug).resolve()
    try:
        pdir.relative_to(user_root)
        pdir.relative_to(base_root)
        if pdir == user_root or pdir == base_root:
            return False
    except ValueError:
        return False
        
    if pdir.exists():
        shutil.rmtree(pdir, ignore_errors=True)
        return True
    return False

def create_zip_archive(user_id: int, slug: str) -> io.BytesIO:
    pdir = get_user_project_dir(user_id, slug)
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for file_path in pdir.rglob("*"):
            if file_path.is_file() and not file_path.is_symlink():
                fname = file_path.name
                if fname == "build.log" or fname.startswith(".") or fname in PROTECTED_FILES:
                    continue
                arcname = file_path.relative_to(pdir)
                zf.write(file_path, arcname)
    zip_buffer.seek(0)
    return zip_buffer
