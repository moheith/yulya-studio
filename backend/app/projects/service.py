"""
Project service for Yulya Studio V2.
Handles filesystem operations, starter game initialization, atomic snapshots, and patch application.
"""

import os
import io
import shutil
import zipfile
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime, timezone

from backend.app.core.config import settings
from backend.app.core.errors import AppError, ErrorCategory
from backend.app.projects.sanitizer import (
    resolve_project_path,
    resolve_file_path,
    sanitize_game_code,
    validate_slug
)
from backend.app.projects.manifest import load_manifest, save_manifest


STARTER_INDEX_HTML = """<!DOCTYPE html>
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
</html>
"""

STARTER_STYLE_CSS = """* {
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
}
"""

STARTER_APP_JS = """// Neon Dodge - Sandboxed HTML5 Canvas Game
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
  const speed = 2 + Math.random() * 2 + (score / 500);
  enemies.push({
    x, y,
    radius: 8 + Math.random() * 6,
    vx: Math.cos(angle) * speed,
    vy: Math.sin(angle) * speed,
    color: '#f43f5e'
  });
}

function createExplosion(x, y, color) {
  for (let i = 0; i < 16; i++) {
    const angle = Math.random() * Math.PI * 2;
    const speed = 1 + Math.random() * 4;
    particles.push({
      x, y,
      vx: Math.cos(angle) * speed,
      vy: Math.sin(angle) * speed,
      life: 30,
      maxLife: 30,
      color
    });
  }
}

function update() {
  if (gameOver) return;

  // Controls
  player.vx = 0;
  player.vy = 0;
  if (keys['KeyW'] || keys['ArrowUp']) player.vy -= player.speed;
  if (keys['KeyS'] || keys['ArrowDown']) player.vy += player.speed;
  if (keys['KeyA'] || keys['ArrowLeft']) player.vx -= player.speed;
  if (keys['KeyD'] || keys['ArrowRight']) player.vx += player.speed;

  player.x += player.vx;
  player.y += player.vy;

  // Boundary clamp
  player.x = Math.max(player.radius, Math.min(width - player.radius, player.x));
  player.y = Math.max(player.radius, Math.min(height - player.radius, player.y));

  // Enemy spawner
  frameCount++;
  if (frameCount % Math.max(20, 60 - Math.floor(score / 100)) === 0) {
    spawnEnemy();
  }

  // Update enemies
  for (let i = enemies.length - 1; i >= 0; i--) {
    const e = enemies[i];
    e.x += e.vx;
    e.y += e.vy;

    // Collision with player
    const dist = Math.hypot(player.x - e.x, player.y - e.y);
    if (dist < player.radius + e.radius) {
      createExplosion(player.x, player.y, player.color);
      endGame();
      return;
    }

    // Clean up out of bounds
    if (e.x < -50 || e.x > width + 50 || e.y < -50 || e.y > height + 50) {
      enemies.splice(i, 1);
    }
  }

  // Update particles
  for (let i = particles.length - 1; i >= 0; i--) {
    const p = particles[i];
    p.x += p.vx;
    p.y += p.vy;
    p.life--;
    if (p.life <= 0) particles.splice(i, 1);
  }

  score++;
  scoreEl.innerText = `SCORE: ${score}`;
  if (score > highScore) {
    highScore = score;
    highScoreEl.innerText = `HIGH: ${highScore}`;
  }
}

function render() {
  ctx.clearRect(0, 0, width, height);

  // Draw player
  if (!gameOver) {
    ctx.shadowBlur = 15;
    ctx.shadowColor = player.color;
    ctx.fillStyle = player.color;
    ctx.beginPath();
    ctx.arc(player.x, player.y, player.radius, 0, Math.PI * 2);
    ctx.fill();
  }

  // Draw enemies
  for (const e of enemies) {
    ctx.shadowBlur = 10;
    ctx.shadowColor = e.color;
    ctx.fillStyle = e.color;
    ctx.beginPath();
    ctx.arc(e.x, e.y, e.radius, 0, Math.PI * 2);
    ctx.fill();
  }

  // Draw particles
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
  finalScoreEl.innerText = `Score: ${score}`;
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
loop();
"""


def init_starter_project(user_id: int, slug: str, title: Optional[str] = None) -> Path:
    """Initializes a new game repository with standard starter files."""
    project_dir = resolve_project_path(user_id, slug)
    project_dir.mkdir(parents=True, exist_ok=True)

    # Write core entrypoints
    (project_dir / "index.html").write_text(STARTER_INDEX_HTML, encoding="utf-8")
    (project_dir / "style.css").write_text(STARTER_STYLE_CSS, encoding="utf-8")
    (project_dir / "app.js").write_text(STARTER_APP_JS, encoding="utf-8")

    # Write manifest
    manifest = load_manifest(project_dir)
    manifest["slug"] = slug
    manifest["title"] = title or slug.replace("-", " ").title()
    manifest["genre"] = "arcade"
    manifest["engine"] = "canvas2d"
    manifest["systems"] = ["movement", "enemy_spawner", "collision_detection", "particles", "score"]
    manifest["controls"] = ["WASD / Arrow Keys", "Mouse"]
    save_manifest(project_dir, manifest)

    return project_dir


def get_project_files(user_id: int, slug: str) -> Dict[str, str]:
    """Reads all text-based source files in the project."""
    project_dir = resolve_project_path(user_id, slug)
    if not project_dir.exists():
        return {}

    files: Dict[str, str] = {}
    for path in project_dir.rglob("*"):
        if path.is_file():
            rel_path = path.relative_to(project_dir).as_posix()
            ext = path.suffix.lower()
            if ext in {".html", ".css", ".js", ".mjs", ".json", ".svg", ".txt"}:
                try:
                    files[rel_path] = path.read_text(encoding="utf-8")
                except Exception:
                    pass
    return files


def read_project_file(user_id: int, slug: str, relative_path: str) -> str:
    """Reads a single authorized file within the project."""
    project_dir = resolve_project_path(user_id, slug)
    target_path = resolve_file_path(project_dir, relative_path)
    if not target_path.exists():
        raise AppError(ErrorCategory.INVALID_INPUT, f"File '{relative_path}' not found in project.")
    return target_path.read_text(encoding="utf-8")


def write_project_file(user_id: int, slug: str, relative_path: str, content: str) -> None:
    """Writes or overwrites an authorized file with safety and sanitization."""
    project_dir = resolve_project_path(user_id, slug)
    target_path = resolve_file_path(project_dir, relative_path)

    if len(content.encode("utf-8")) > settings.MAX_FILE_SIZE:
        raise AppError(ErrorCategory.INVALID_INPUT, f"File size exceeds maximum allowed ({settings.MAX_FILE_SIZE} bytes).")

    sanitized, _ = sanitize_game_code(content)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(sanitized, encoding="utf-8")


def apply_patch(user_id: int, slug: str, relative_path: str, search_str: str, replace_str: str) -> None:
    """Applies an exact search-and-replace patch to a file."""
    current_content = read_project_file(user_id, slug, relative_path)
    if search_str not in current_content:
        raise AppError(
            ErrorCategory.STALE_VERSION,
            f"Patch context mismatch in '{relative_path}': target search string was not found.",
            recoverable=True
        )

    count = current_content.count(search_str)
    if count > 1:
        raise AppError(
            ErrorCategory.CONFLICT,
            f"Ambiguous patch in '{relative_path}': search string matches {count} locations.",
            recoverable=True
        )

    new_content = current_content.replace(search_str, replace_str, 1)
    write_project_file(user_id, slug, relative_path, new_content)


def delete_project_file(user_id: int, slug: str, relative_path: str) -> None:
    """Deletes an authorized file inside the project (protected entrypoint index.html cannot be deleted)."""
    clean_rel = relative_path.strip().replace("\\", "/").lstrip("/")
    if clean_rel == "index.html":
        raise AppError(ErrorCategory.PERMISSION_DENIED, "The primary game entrypoint 'index.html' cannot be deleted.")

    project_dir = resolve_project_path(user_id, slug)
    target_path = resolve_file_path(project_dir, relative_path)
    if target_path.exists():
        if target_path.is_file():
            target_path.unlink()
        elif target_path.is_dir():
            shutil.rmtree(target_path)


def list_project_files(user_id: int, slug: str) -> List[Dict[str, Any]]:
    """Lists all files in project with path, size, and type."""
    project_dir = resolve_project_path(user_id, slug)
    if not project_dir.exists():
        return []

    results: List[Dict[str, Any]] = []
    for item in sorted(project_dir.rglob("*")):
        rel = item.relative_to(project_dir).as_posix()
        results.append({
            "path": rel,
            "name": item.name,
            "is_dir": item.is_dir(),
            "size": item.stat().st_size if item.is_file() else 0,
            "extension": item.suffix.lower() if item.is_file() else ""
        })
    return results


def search_project_files(user_id: int, slug: str, query: str) -> List[Dict[str, Any]]:
    """Searches project source files for a given text query."""
    files = get_project_files(user_id, slug)
    matches: List[Dict[str, Any]] = []
    q_lower = query.lower()
    for rel_path, content in files.items():
        lines = content.splitlines()
        for idx, line in enumerate(lines, start=1):
            if q_lower in line.lower():
                matches.append({
                    "file": rel_path,
                    "line": idx,
                    "content": line.strip()
                })
    return matches


def create_snapshot(user_id: int, slug: str) -> Dict[str, str]:
    """Takes an in-memory snapshot of current project files for transactional rollback."""
    return get_project_files(user_id, slug)


def restore_snapshot(user_id: int, slug: str, snapshot: Dict[str, str]) -> None:
    """Restores project files from an in-memory snapshot if build validation fails."""
    project_dir = resolve_project_path(user_id, slug)
    for rel_path, content in snapshot.items():
        target = resolve_file_path(project_dir, rel_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")


def export_project_zip(user_id: int, slug: str) -> io.BytesIO:
    """Packages the project directory into a ZIP archive buffer."""
    project_dir = resolve_project_path(user_id, slug)
    if not project_dir.exists():
        raise AppError(ErrorCategory.INVALID_INPUT, "Project directory does not exist.")

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for file_path in project_dir.rglob("*"):
            if file_path.is_file():
                rel_path = file_path.relative_to(project_dir).as_posix()
                zip_file.write(file_path, arcname=rel_path)

    zip_buffer.seek(0)
    return zip_buffer
