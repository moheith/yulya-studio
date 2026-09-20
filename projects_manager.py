import os
import re
import io
import shutil
import zipfile
from pathlib import Path
import config

def get_user_project_dir(user_id: int, slug: str) -> Path:
    safe_slug = re.sub(r'[^a-zA-Z0-9_-]', '', slug).lower()
    project_dir = config.PROJECTS_DIR / str(user_id) / safe_slug
    # Security check: ensure path is strictly inside config.PROJECTS_DIR
    resolved = project_dir.resolve()
    if not str(resolved).startswith(str(config.PROJECTS_DIR.resolve())):
        raise PermissionError("Path traversal attempt detected.")
    project_dir.mkdir(parents=True, exist_ok=True)
    return project_dir

def write_project_file(user_id: int, slug: str, filename: str, content: str) -> str:
    safe_name = os.path.basename(filename)
    pdir = get_user_project_dir(user_id, slug)
    target = pdir / safe_name
    target.write_text(content, encoding="utf-8")
    return safe_name

def read_project_file(user_id: int, slug: str, filename: str) -> str:
    safe_name = os.path.basename(filename)
    pdir = get_user_project_dir(user_id, slug)
    target = pdir / safe_name
    if not target.exists():
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

def create_starter_game(user_id: int, username: str, slug: str, title: str):
    """Generates a clean starter template with neon canvas and retro styling."""
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
  <div class="game-container">
    <header>
      <h1>{title}</h1>
      <p class="author">Created by <span>@{username}</span> with Yulya Studio</p>
    </header>
    <main>
      <canvas id="gameCanvas" width="600" height="400"></canvas>
      <div class="hud">
        <div class="score">Score: <span id="scoreVal">0</span></div>
        <button id="startBtn" class="btn">Play / Reset</button>
      </div>
      <div class="instructions">Use [Arrow Keys] or [WASD] to control. Built with voice in Yulya Studio!</div>
    </main>
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

body {
  background: #0d0221;
  color: #ffffff;
  font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
  display: flex;
  justify-content: center;
  align-items: center;
  min-height: 100vh;
  overflow: hidden;
}

.game-container {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  background: rgba(20, 10, 40, 0.85);
  border: 1px solid rgba(155, 89, 182, 0.4);
  padding: 24px;
  border-radius: 16px;
  box-shadow: 0 0 30px rgba(155, 89, 182, 0.25), inset 0 0 15px rgba(155, 89, 182, 0.1);
  backdrop-filter: blur(10px);
}

header h1 {
  font-size: 1.8rem;
  color: #00f0ff;
  text-shadow: 0 0 10px rgba(0, 240, 255, 0.6);
  letter-spacing: 1px;
}

.author {
  font-size: 0.85rem;
  color: #a0a0c0;
}

.author span {
  color: #ff007f;
  font-weight: bold;
}

canvas {
  background: #050110;
  border: 2px solid #00f0ff;
  border-radius: 8px;
  box-shadow: 0 0 15px rgba(0, 240, 255, 0.3);
  display: block;
}

.hud {
  display: flex;
  justify-content: space-between;
  width: 100%;
  align-items: center;
  padding: 8px 12px;
}

.score {
  font-size: 1.2rem;
  font-weight: bold;
  color: #39ff14;
  text-shadow: 0 0 8px rgba(57, 255, 20, 0.5);
}

.btn {
  background: linear-gradient(135deg, #ff007f, #9b59b6);
  color: white;
  border: none;
  padding: 8px 18px;
  border-radius: 8px;
  font-weight: bold;
  cursor: pointer;
  transition: transform 0.15s, box-shadow 0.15s;
}

.btn:hover {
  transform: scale(1.04);
  box-shadow: 0 0 12px rgba(255, 0, 127, 0.6);
}

.instructions {
  font-size: 0.8rem;
  color: #8888aa;
}
"""

    js = """// Starter Neon Dodge Game
const canvas = document.getElementById('gameCanvas');
const ctx = canvas.getContext('2d');
const scoreEl = document.getElementById('scoreVal');
const startBtn = document.getElementById('startBtn');

let score = 0;
let gameOver = false;
let running = false;

const player = {
  x: canvas.width / 2,
  y: canvas.height - 40,
  width: 24,
  height: 24,
  speed: 5,
  color: '#00f0ff'
};

let enemies = [];
let keys = {};

window.addEventListener('keydown', e => keys[e.key.toLowerCase()] = true);
window.addEventListener('keyup', e => keys[e.key.toLowerCase()] = false);

function spawnEnemy() {
  if (!running || gameOver) return;
  enemies.push({
    x: Math.random() * (canvas.width - 20),
    y: -20,
    size: Math.random() * 16 + 12,
    speed: Math.random() * 3 + 2,
    color: '#ff007f'
  });
}

setInterval(spawnEnemy, 600);

function update() {
  if (!running || gameOver) return;

  if (keys['arrowleft'] || keys['a']) player.x -= player.speed;
  if (keys['arrowright'] || keys['d']) player.x += player.speed;
  if (keys['arrowup'] || keys['w']) player.y -= player.speed;
  if (keys['arrowdown'] || keys['s']) player.y += player.speed;

  // Clamping
  player.x = Math.max(0, Math.min(canvas.width - player.width, player.x));
  player.y = Math.max(0, Math.min(canvas.height - player.height, player.y));

  for (let i = enemies.length - 1; i >= 0; i--) {
    let e = enemies[i];
    e.y += e.speed;

    // Collision
    if (
      player.x < e.x + e.size &&
      player.x + player.width > e.x &&
      player.y < e.y + e.size &&
      player.y + player.height > e.y
    ) {
      gameOver = true;
    }

    // Passed
    if (e.y > canvas.height) {
      enemies.splice(i, 1);
      score += 10;
      scoreEl.innerText = score;
    }
  }
}

function draw() {
  ctx.clearRect(0, 0, canvas.width, canvas.height);

  // Draw Player
  ctx.shadowBlur = 15;
  ctx.shadowColor = player.color;
  ctx.fillStyle = player.color;
  ctx.fillRect(player.x, player.y, player.width, player.height);

  // Draw Enemies
  for (let e of enemies) {
    ctx.shadowColor = e.color;
    ctx.fillStyle = e.color;
    ctx.beginPath();
    ctx.arc(e.x + e.size/2, e.y + e.size/2, e.size/2, 0, Math.PI * 2);
    ctx.fill();
  }
  ctx.shadowBlur = 0;

  if (gameOver) {
    ctx.fillStyle = 'rgba(0, 0, 0, 0.7)';
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.fillStyle = '#ff007f';
    ctx.font = '28px sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText('GAME OVER', canvas.width / 2, canvas.height / 2 - 10);
    ctx.fillStyle = '#ffffff';
    ctx.font = '16px sans-serif';
    ctx.fillText('Press Play / Reset to Try Again', canvas.width / 2, canvas.height / 2 + 25);
  }

  if (running) requestAnimationFrame(() => { update(); draw(); });
}

startBtn.addEventListener('click', () => {
  player.x = canvas.width / 2;
  player.y = canvas.height - 40;
  enemies = [];
  score = 0;
  scoreEl.innerText = '0';
  gameOver = false;
  running = true;
  update();
  draw();
});

draw();
"""

    (pdir / "index.html").write_text(html, encoding="utf-8")
    (pdir / "style.css").write_text(css, encoding="utf-8")
    (pdir / "app.js").write_text(js, encoding="utf-8")
    return ["index.html", "style.css", "app.js"]

def rename_project_dir(user_id: int, old_slug: str, new_slug: str) -> bool:
    old_pdir = config.PROJECTS_DIR / str(user_id) / re.sub(r'[^a-zA-Z0-9_-]', '', old_slug).lower()
    new_pdir = config.PROJECTS_DIR / str(user_id) / re.sub(r'[^a-zA-Z0-9_-]', '', new_slug).lower()
    if not old_pdir.exists():
        return False
    if new_pdir.exists() and old_pdir != new_pdir:
        shutil.rmtree(new_pdir)
    old_pdir.rename(new_pdir)
    return True

def delete_project_dir(user_id: int, slug: str) -> bool:
    pdir = config.PROJECTS_DIR / str(user_id) / re.sub(r'[^a-zA-Z0-9_-]', '', slug).lower()
    if pdir.exists():
        shutil.rmtree(pdir)
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
