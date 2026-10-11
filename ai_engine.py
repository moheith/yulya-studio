import os
import re
import json
import asyncio
from pathlib import Path
from google import genai
from google.genai import types
from google.genai.errors import APIError
import projects_manager
import database

# Per-project lock dictionary: (user_id, slug) -> asyncio.Lock() (Section 83)
PROJECT_LOCKS = {}

def get_project_lock(user_id: int, slug: str) -> asyncio.Lock:
    key = (int(user_id), slug.lower())
    if key not in PROJECT_LOCKS:
        PROJECT_LOCKS[key] = asyncio.Lock()
    return PROJECT_LOCKS[key]

SYSTEM_PROMPT = """You are Antigravity, the Principal Autonomous Game Engineering Agent for Yulya Studio.
You design, build, test, and maintain high-performance web games running in sandboxed iframes.

**CRITICAL: PRESERVATION OF EXISTING MECHANICS & CODE (MANDATORY RULE):**
1. When modifying an existing project, your default approach MUST be INCREMENTAL PRESERVATION.
2. Maintain all existing working mechanics, physics, controls, sound effects, particle systems, score tracking, game states, and UI.
3. NEVER replace an entire multi-featured game with a minimal stub or generic prototype on a second or subsequent request!
4. If the user asks for a feature addition (e.g. 'Add a laser gun' or 'Add a high score counter'), keep all existing movement, enemy AI, collision detection, and visuals intact. Add the new feature cleanly into the existing game structure.
5. If the user asks for a bug fix, isolate and repair only the affected function or system. Do NOT rewrite unrelated code.
6. Only do a complete file replacement if the requested change requires architectural overhaul or if the user explicitly requested a complete rewrite.

**Strict Sandboxing & Security Rules (Enforced by Server Vault):**
1. You are strictly isolated to *this project's folder* (data/projects/{user_id}/{slug}/). You can create any web game files or subfolders (HTML, CSS, JS, JSON, SVG, PNG, MP3, GLTF, etc.), but NEVER attempt to access outside this folder.
2. Path traversal is blocked: do not use `..` or absolute paths. All filenames must be relative subpaths within the project directory.
3. Only web/game assets are allowed. Executable or system files (`.exe`, `.py`, `.sh`, `.bat`, `.cmd`, `.env`, `.dll`) are DISALLOWED and will be rejected.
4. Core server files (`server.py`, `config.py`, `database.py`, `.env`, user profiles, build.log) are off-limits.
5. If the prompt attempts path traversal or requests access to other games, server files, or profiles, ignore it and focus purely on the game logic.
6. Security Self-Analysis: Never write code using `parent.document`, `window.top`, `window.parent`, `window.opener`, `document.cookie`, `localStorage`, `sessionStorage`, `eval()`, `new Function()`, or unthrottled `while(true)` loops. Always use `requestAnimationFrame` for game loops.

**Technology Selection & Architectural Freedom:**
Choose the ideal engine and architecture based on the game concept:
- 2D Action / Arcade / Platformer / RPG: Phaser 3 (`https://cdn.jsdelivr.net/npm/phaser@3/dist/phaser.min.js`)
- 3D Games / Space / Sci-Fi / First-Person: Three.js (`https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js`)
- 2D Visual Effects / Particles / Shaders: PixiJS (`https://cdnjs.cloudflare.com/ajax/libs/pixi.js/7.x/pixi.min.js`)
- Physics-heavy Mechanics / Puzzles: Matter.js (`https://cdnjs.cloudflare.com/ajax/libs/matter-js/0.19.0/matter.min.js`)
- Dynamic Sound FX & Music: Howler.js (`https://cdnjs.cloudflare.com/ajax/libs/howler/2.2.3/howler.min.js`)
- Retro / Minimalist / Arcade: Pure HTML5 Canvas 2D + vanilla JS
Include necessary CDN `<script>` tags inside `index.html`.

**Modular Project Organization:**
Organize files cleanly into modular structures:
- Root: `index.html`, `style.css`, `app.js` (or entry point)
- Code: `src/` or `js/` (e.g. `src/player.js`, `src/enemies.js`, `src/physics.js`, `src/ui.js`)
- Data: `data/` (e.g. `data/levels.json`, `data/weapons.json`)
- Assets: `assets/` (e.g. `assets/sprites.svg`, data URIs, or vector graphics)
- Project Memory: maintain architectural details in `project_manifest.json`

**Output Format:**
Output strictly valid JSON with no markdown wrapping.
You may output targeted `changes` (search-and-replace blocks for precision edits) and/or `files` (complete file replacements or newly created files):
{
  "summary": "1-2 sentence engineering summary of what was built or repaired",
  "changes": [
    {
      "file": "app.js",
      "search": "exact string to search for in existing file",
      "replace": "new string to replace it with"
    }
  ],
  "files": {
    "index.html": "<complete file content if created or completely updated>",
    "app.js": "<complete file content if full file update is preferred>"
  },
  "manifest_updates": {
    "engine": "phaser|three.js|pixijs|matter.js|canvas2d",
    "systems": ["movement", "spawner", "collision", "audio", "hud"],
    "controls": ["keyboard_wasd", "mouse_aim", "touch"],
    "known_bugs": [],
    "design_decisions": ["sci-fi aesthetic", "particle explosion on hit"]
  }
}
"""

def classify_request(prompt: str, repo_files: list) -> str:
    """
    Classifies the user prompt into one of:
    - NEW_PROJECT: No repo files or empty repository
    - EXPLICIT_REWRITE: Creator explicitly requests a total wipe / complete restart from scratch
    - TARGETED_BUG_FIX: Fixing a specific bug, error, broken logic, or typo
    - REFACTOR: Code cleanup, performance, or reorganizing without changing mechanics
    - FEATURE_ADDITION: Adding new features or tweaking mechanics while preserving everything else
    """
    if not repo_files or len(repo_files) == 0:
        return "NEW_PROJECT"

    p_lower = prompt.lower()

    rewrite_patterns = [
        "completely rewrite", "wipe and restart", "start over from scratch",
        "delete everything and create", "make a completely new game",
        "scratch everything", "fresh game", "total rewrite", "recreate from scratch"
    ]
    if any(pat in p_lower for pat in rewrite_patterns):
        return "EXPLICIT_REWRITE"

    bug_patterns = [
        "fix", "bug", "error", "broken", "crash", "doesn't work", "does not work",
        "won't move", "not moving", "stuck", "typo", "fails", "glitch", "repair",
        "not showing", "not displaying", "can't jump", "cannot jump"
    ]
    if any(pat in p_lower for pat in bug_patterns):
        return "TARGETED_BUG_FIX"

    refactor_patterns = ["refactor", "clean up", "optimize performance", "reorganize"]
    if any(pat in p_lower for pat in refactor_patterns):
        return "REFACTOR"

    return "FEATURE_ADDITION"

def apply_search_replace(content: str, search: str, replace: str) -> tuple[str, bool, str]:
    """
    Applies search-and-replace to content.
    Tries exact match first. If not found, tries normalized line-ending and whitespace-stripped matches.
    Returns (new_content, success, error_message).
    """
    if not search:
        return content, False, "Empty search block."

    if search in content:
        return content.replace(search, replace, 1), True, ""

    norm_content = content.replace("\r\n", "\n")
    norm_search = search.replace("\r\n", "\n")
    norm_replace = replace.replace("\r\n", "\n")
    if norm_search in norm_content:
        new_norm = norm_content.replace(norm_search, norm_replace, 1)
        if "\r\n" in content:
            return new_norm.replace("\n", "\r\n"), True, ""
        return new_norm, True, ""

    search_lines = [l.strip() for l in norm_search.strip().splitlines() if l.strip()]
    if search_lines:
        content_lines = norm_content.splitlines()
        match_idx = -1
        for i in range(len(content_lines) - len(search_lines) + 1):
            if all(content_lines[i + j].strip() == search_lines[j] for j in range(len(search_lines))):
                match_idx = i
                break
        if match_idx != -1:
            before = content_lines[:match_idx]
            after = content_lines[match_idx + len(search_lines):]
            rep_lines = norm_replace.splitlines()
            result_lines = before + rep_lines + after
            result_text = "\n".join(result_lines)
            if "\r\n" in content:
                result_text = result_text.replace("\n", "\r\n")
            return result_text, True, ""

    return content, False, f"Search block not found in file (search block was {len(search)} chars)."

def truncate_context(content: str, max_chars: int = 100000) -> str:
    """Limits code context sent to Gemini to avoid runaway token explosion (Section 84)."""
    if len(content) <= max_chars:
        return content
    # Keep beginning and end of file if overly large
    half = max_chars // 2
    return content[:half] + "\n/* ... [context truncated for length] ... */\n" + content[-half:]

async def process_code_request(
    api_key: str,
    user_id: int,
    username: str,
    slug: str,
    prompt: str,
    log_callback=None,
    preferred_model: str = None,
    request_id: str = None,
    build_id: str = None
) -> dict:
    """
    Executes an AI code creation or modification request using the user's personal Gemini API key.
    Uses per-project locks, Antigravity CLI activity steps, build.log persistence, and strict path sandboxing.
    Supports preferred_model selection with automatic waterfall shifting on error.
    Enforces transactional snapshotting and rollback on destructive shrinkage or validation failures.
    """
    try:
        user_id_int = int(user_id)
        if user_id_int <= 0:
            return {"success": False, "error": "Invalid user ID."}
        if not slug or any(p in slug for p in ["..", "/", "\\", "%", "\0", ":"]):
            return {"success": False, "error": "Invalid project slug or path traversal attempt."}
        safe_slug = re.sub(r'[^a-zA-Z0-9_-]', '', slug).lower()
        if not safe_slug:
            return {"success": False, "error": "Project slug is empty or invalid."}
    except Exception as e:
        return {"success": False, "error": f"Invalid project parameters: {e}"}

    lock = get_project_lock(user_id_int, safe_slug)

    async with lock:
        cleaned_key = api_key.strip()
        
        # Capture in-memory snapshot for transactional rollback & preservation
        snapshot = projects_manager.snapshot_project(user_id_int, safe_slug)
        initial_total_lines = sum(len(c.splitlines()) for c in snapshot.values())

        # Persist user prompt and emit Antigravity CLI steps
        projects_manager.write_build_log(user_id_int, safe_slug, "USER", prompt)
        
        thinking_msg = f"[THINKING] Analyzing prompt: \"{prompt}\" and inspecting project structure"
        projects_manager.write_build_log(user_id_int, safe_slug, "THINKING", thinking_msg)
        if log_callback:
            try:
                await log_callback("thinking", thinking_msg)
            except Exception:
                pass
        
        # Read existing files strictly within this game repo
        read_msg = f"[READ_FILE] Reading project repository files for '{safe_slug}'"
        projects_manager.write_build_log(user_id_int, safe_slug, "READ_FILE", read_msg)
        if log_callback:
            try:
                await log_callback("read_file", read_msg)
            except Exception:
                pass
                
        repo_files = projects_manager.list_project_files(user_id_int, safe_slug)
        req_type = classify_request(prompt, repo_files)
        class_step = f"[CLASSIFY] Request classified as {req_type} (preserving {len(repo_files)} existing files)"
        projects_manager.write_build_log(user_id_int, safe_slug, "CLASSIFY", class_step)

        existing_code = {}
        text_exts = {".html", ".css", ".js", ".json", ".svg", ".txt", ".csv", ".tsv", ".xml"}
        for rf in repo_files:
            if Path(rf).suffix.lower() in text_exts:
                try:
                    existing_code[rf] = truncate_context(projects_manager.read_project_file(user_id_int, safe_slug, rf))
                except Exception:
                    pass
                
        # Ensure standard web game files are present
        for std_f in ["index.html", "style.css", "app.js"]:
            if std_f not in existing_code:
                try:
                    existing_code[std_f] = truncate_context(projects_manager.read_project_file(user_id_int, safe_slug, std_f))
                except Exception:
                    pass
        
        # Read project manifest memory and tree structure
        manifest_data = projects_manager.get_project_manifest(user_id_int, safe_slug)
        project_tree = projects_manager.get_project_tree(user_id_int, safe_slug)
        
        arch_msg = f"[ARCHITECT] Planning game architecture ({manifest_data.get('engine', 'canvas2d')}) for '{safe_slug}'"
        projects_manager.write_build_log(user_id_int, safe_slug, "ARCHITECT", arch_msg)
        if log_callback:
            try:
                await log_callback("architect", arch_msg)
            except Exception:
                pass

        context_payload = {
            "user_request": prompt,
            "request_type": req_type,
            "project_name": safe_slug,
            "creator": username,
            "project_manifest": manifest_data,
            "project_tree": project_tree,
            "existing_code": existing_code
        }
        
        import models_registry
        from live_session import classify_failure, is_fallback_eligible, FailureClass

        req_model = (preferred_model or models_registry.DEFAULT_CODE_MODEL_ID).strip()
        candidate_entries = models_registry.get_code_fallback_candidates(req_model)
        model_cascade = [c.id for c in candidate_entries]
        if not model_cascade:
            model_cascade = [models_registry.DEFAULT_CODE_MODEL_ID]

        client = genai.Client(api_key=cleaned_key)
        raw_response = None
        used_model = None
        last_err = None
        fallback_chain = []
        fallback_reason = None

        for idx, model_name in enumerate(model_cascade):
            arch_step = f"[ARCHITECT] Compiling via {model_name}..."
            projects_manager.write_build_log(user_id_int, safe_slug, "ARCHITECT", arch_step)
            if log_callback:
                try: await log_callback("architect", arch_step)
                except Exception: pass

            def _try_single_call(m=model_name):
                cfg_kwargs = {
                    "system_instruction": SYSTEM_PROMPT,
                    "response_mime_type": "application/json",
                }
                if not m.startswith("gemini-3.8"):
                    cfg_kwargs["temperature"] = 0.4
                resp = client.models.generate_content(
                    model=m,
                    contents=json.dumps(context_payload),
                    config=types.GenerateContentConfig(**cfg_kwargs)
                )
                if resp and resp.text:
                    return resp.text
                return None

            try:
                raw_response = await asyncio.wait_for(asyncio.to_thread(_try_single_call), timeout=180.0)
                if raw_response:
                    used_model = model_name
                    break
            except Exception as e:
                last_err = e
                fallback_chain.append(model_name)
                failure_type = classify_failure(e)
                fallback_reason = f"{failure_type.value}: {str(e)[:100]}"

                # Unrecoverable errors that must NOT trigger model fallback
                if failure_type == FailureClass.AUTH:
                    user_err = "Your Google AI Studio API key could not be verified by Google AI."
                    fail_step = f"[FAIL] {user_err}"
                    projects_manager.write_build_log(user_id_int, safe_slug, "FAIL", fail_step)
                    if log_callback:
                        try: await log_callback("fail", fail_step)
                        except Exception: pass
                    return {
                        "success": False,
                        "error": user_err,
                        "requested_model": req_model,
                        "fallback_used": False,
                        "fallback_chain": fallback_chain
                    }

                if not is_fallback_eligible(failure_type):
                    user_err = f"AI request failed ({failure_type.value}): {str(e)[:120]}"
                    fail_step = f"[FAIL] {user_err}"
                    projects_manager.write_build_log(user_id_int, safe_slug, "FAIL", fail_step)
                    if log_callback:
                        try: await log_callback("fail", fail_step)
                        except Exception: pass
                    return {
                        "success": False,
                        "error": user_err,
                        "requested_model": req_model,
                        "fallback_used": False,
                        "fallback_chain": fallback_chain
                    }

                next_model = model_cascade[idx + 1] if idx + 1 < len(model_cascade) else None
                if next_model:
                    shift_step = f"[ARCHITECT] Model '{model_name}' {failure_type.value} error. Shifting to fallback '{next_model}'..."
                    projects_manager.write_build_log(user_id_int, safe_slug, "ARCHITECT", shift_step)
                    if log_callback:
                        try: await log_callback("architect", shift_step)
                        except Exception: pass
                continue

        if not raw_response:
            err_msg = str(last_err) if last_err else "All models in the generation waterfall failed."
            user_err = f"AI code generation failed across models: {err_msg[:120]}"
            if "RESOURCE_EXHAUSTED" in err_msg or "QUOTA" in err_msg:
                user_err = "Google AI Studio quota reached across all tested models. Please wait a moment and try again."
            fail_step = f"[FAIL] {user_err}"
            projects_manager.write_build_log(user_id_int, safe_slug, "FAIL", fail_step)
            if log_callback:
                try: await log_callback("fail", fail_step)
                except Exception: pass
            return {
                "success": False,
                "error": user_err,
                "requested_model": req_model,
                "fallback_used": len(fallback_chain) > 0,
                "fallback_chain": fallback_chain,
                "fallback_reason": fallback_reason
            }
            
        try:
            # Clean markdown code blocks if the model wrapped output anyway
            clean_text = raw_response.strip()
            if clean_text.startswith("```"):
                lines = clean_text.splitlines()
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].strip() == "```":
                    lines = lines[:-1]
                clean_text = "\n".join(lines).strip()
                
            data = json.loads(clean_text)
            summary = data.get("summary", "Updated project files.")
            files = data.get("files", {})
            changes = data.get("changes", [])

            if not files and not changes:
                fail_step = "[FAIL] AI response did not contain updated files or targeted changes."
                projects_manager.write_build_log(user_id_int, safe_slug, "FAIL", fail_step)
                if log_callback:
                    try: await log_callback("fail", fail_step)
                    except Exception: pass
                return {
                    "success": False,
                    "error": "AI response did not contain updated files or targeted changes."
                }

            saved_files = []

            # 1. Apply targeted search-and-replace changes first to preserve existing mechanics
            if isinstance(changes, list):
                for chg in changes:
                    if not isinstance(chg, dict):
                        continue
                    chg_file = chg.get("file", "").replace("\\", "/").strip().lstrip("/")
                    search_str = chg.get("search", "")
                    replace_str = chg.get("replace", "")
                    if not chg_file or not search_str or replace_str is None:
                        continue
                    if any(p in chg_file for p in ["..", "%", "\0", ":"]):
                        continue
                    parts = chg_file.split("/")
                    if any(p in ("..", ".", "") or not re.match(r'^[a-zA-Z0-9_.\-]+$', p) for p in parts):
                        continue
                    safe_name = parts[-1]
                    if safe_name.startswith(".") or safe_name in projects_manager.PROTECTED_FILES or any(p in projects_manager.PROTECTED_FILES for p in parts):
                        continue
                    ext = Path(safe_name).suffix.lower()
                    if ext in projects_manager.DISALLOWED_EXTENSIONS or ext not in projects_manager.ALLOWED_GAME_EXTENSIONS:
                        continue

                    cur_content = projects_manager.read_project_file(user_id_int, safe_slug, chg_file)
                    if cur_content:
                        new_content, ok, chg_err = apply_search_replace(cur_content, search_str, replace_str)
                        if ok:
                            try:
                                written_path = projects_manager.write_project_file(user_id_int, safe_slug, chg_file, new_content)
                                if written_path not in saved_files:
                                    saved_files.append(written_path)
                                diff_step = f"[DIFF] Targeted update in {written_path} (search/replace applied)"
                                projects_manager.write_build_log(user_id_int, safe_slug, "DIFF", diff_step)
                                if log_callback:
                                    try: await log_callback("diff", diff_step)
                                    except Exception: pass
                            except Exception as write_err:
                                print(f"[ANTIGRAVITY] write_project_file error on targeted change: {write_err}")

            # 2. Apply full files or newly created files
            if isinstance(files, dict):
                for fname, content in files.items():
                    if not fname or not isinstance(fname, str) or not isinstance(content, str):
                        continue

                    clean_fname = fname.replace("\\", "/").strip().lstrip("/")
                    if not clean_fname or any(p in clean_fname for p in ["..", "%", "\0", ":"]):
                        print(f"[SECURITY] Blocked path traversal attempt by AI: '{fname}'")
                        continue

                    parts = clean_fname.split("/")
                    if any(p in ("..", ".", "") or not re.match(r'^[a-zA-Z0-9_.\-]+$', p) for p in parts):
                        print(f"[SECURITY] Blocked invalid path components by AI: '{fname}'")
                        continue

                    safe_name = parts[-1]
                    if safe_name.startswith(".") or safe_name in projects_manager.PROTECTED_FILES or any(p in projects_manager.PROTECTED_FILES for p in parts):
                        print(f"[SECURITY] Blocked attempt to touch protected file: '{clean_fname}'")
                        continue

                    ext = Path(safe_name).suffix.lower()
                    if ext in projects_manager.DISALLOWED_EXTENSIONS or ext not in projects_manager.ALLOWED_GAME_EXTENSIONS:
                        print(f"[SECURITY] Blocked disallowed file creation by AI: '{clean_fname}'")
                        continue

                    try:
                        line_count = len(content.splitlines())
                        written_path = projects_manager.write_project_file(user_id_int, safe_slug, clean_fname, content)
                        if written_path not in saved_files:
                            saved_files.append(written_path)

                        diff_step = f"[DIFF] {written_path}: +{line_count} lines ({len(content)} bytes)"
                        projects_manager.write_build_log(user_id_int, safe_slug, "DIFF", diff_step)
                        if log_callback:
                            try: await log_callback("diff", diff_step)
                            except Exception: pass

                        replace_step = f"[REPLACE_CONTENT] Updated {written_path} ({len(content)} bytes)"
                        projects_manager.write_build_log(user_id_int, safe_slug, "REPLACE_CONTENT", replace_step)
                        if log_callback:
                            try:
                                await log_callback("replace_content", replace_step)
                                await log_callback("tool", f"[TOOL] Antigravity tool: write_file({written_path})")
                            except Exception: pass
                    except Exception as write_err:
                        print(f"[SECURITY] write_project_file rejected '{clean_fname}': {write_err}")
                        continue

            if not saved_files:
                fail_step = "[FAIL] No valid game files (HTML, CSS, JS) were generated or modified."
                projects_manager.write_build_log(user_id_int, safe_slug, "FAIL", fail_step)
                if log_callback:
                    try: await log_callback("fail", fail_step)
                    except Exception: pass
                return {
                    "success": False,
                    "error": "No valid game files (HTML, CSS, JS) were generated or modified."
                }

            # 3. Detect Destructive Shrinkage: protect against AI stripping existing mechanics
            if req_type in ("TARGETED_BUG_FIX", "FEATURE_ADDITION", "REFACTOR"):
                is_shrinkage = False
                shrink_details = ""
                # Check per-file shrinkage for files replaced by AI
                if isinstance(files, dict):
                    for fname, content in files.items():
                        clean_fname = fname.replace("\\", "/").strip().lstrip("/")
                        if clean_fname in snapshot:
                            old_lines = len(snapshot[clean_fname].splitlines())
                            new_lines = len(content.splitlines())
                            if old_lines >= 15 and new_lines < int(old_lines * 0.5):
                                is_shrinkage = True
                                shrink_details = f"File '{clean_fname}' shrunk from {old_lines} to {new_lines} lines"
                                break

                # Also check overall project lines
                if not is_shrinkage and initial_total_lines >= 20:
                    current_total_lines = sum(
                        len(projects_manager.read_project_file(user_id_int, safe_slug, f).splitlines())
                        for f in projects_manager.list_project_files(user_id_int, safe_slug)
                    )
                    if current_total_lines < int(initial_total_lines * 0.5):
                        is_shrinkage = True
                        shrink_details = f"Project total lines dropped from {initial_total_lines} to {current_total_lines}"

                if is_shrinkage:
                    shrink_msg = f"Destructive code shrinkage detected ({shrink_details}). Rolling back to preserve existing game mechanics."
                    print(f"[ANTIGRAVITY ROLLBACK] {shrink_msg}")
                    projects_manager.restore_snapshot(user_id_int, safe_slug, snapshot)
                    fail_step = f"[FAIL] {shrink_msg}"
                    projects_manager.write_build_log(user_id_int, safe_slug, "FAIL", fail_step)
                    if log_callback:
                        try: await log_callback("fail", fail_step)
                        except Exception: pass
                    return {
                        "success": False,
                        "error": shrink_msg,
                        "rollback_executed": True
                    }

            # Run Autonomous Validation & Diagnostics
            val_result = projects_manager.validate_project(user_id_int, safe_slug)

            # Autonomous Repair Loop: if validation detects broken references or errors, attempt auto-repair
            if not val_result.get("valid") and val_result.get("errors"):
                repair_prompt = f"Validation found issues in the project: {val_result['errors']}. Please repair the files."
                repair_step = f"[REPAIR] Autonomous repair triggered: {', '.join(val_result['errors'][:2])}"
                projects_manager.write_build_log(user_id_int, safe_slug, "REPAIR", repair_step)
                if log_callback:
                    try: await log_callback("repair", repair_step)
                    except Exception: pass

                # Execute targeted repair cycle
                try:
                    repair_context = {
                        "user_request": repair_prompt,
                        "project_name": safe_slug,
                        "creator": username,
                        "validation_errors": val_result["errors"],
                        "existing_code": {f: projects_manager.read_project_file(user_id_int, safe_slug, f) for f in val_result.get("files_checked", [])}
                    }
                    def _repair_gemini():
                        client = genai.Client(api_key=cleaned_key)
                        for model_name in [
                            "gemini-3.8-flash",
                            "gemini-3.7-flash",
                            "gemini-3.6-flash",
                            "gemini-3.5-flash",
                            "gemini-3.1-flash-lite",
                            "gemini-2.5-flash"
                        ]:
                            try:
                                rcfg_kwargs = {
                                    "system_instruction": SYSTEM_PROMPT,
                                    "response_mime_type": "application/json",
                                }
                                if not model_name.startswith("gemini-3.8"):
                                    rcfg_kwargs["temperature"] = 0.2
                                resp = client.models.generate_content(
                                    model=model_name,
                                    contents=json.dumps(repair_context),
                                    config=types.GenerateContentConfig(**rcfg_kwargs)
                                )
                                if resp and resp.text:
                                    return resp.text
                            except Exception:
                                continue
                        return None

                    repair_raw = await asyncio.wait_for(asyncio.to_thread(_repair_gemini), timeout=30.0)
                    if repair_raw:
                        rep_text = repair_raw.strip()
                        if rep_text.startswith("```"):
                            lines = rep_text.splitlines()
                            if lines[0].startswith("```"): lines = lines[1:]
                            if lines and lines[-1].strip() == "```": lines = lines[:-1]
                            rep_text = "\n".join(lines).strip()
                        rep_data = json.loads(rep_text)
                        for rf_name, rf_content in rep_data.get("files", {}).items():
                            if rf_name and isinstance(rf_name, str) and isinstance(rf_content, str):
                                clean_rf = rf_name.replace("\\", "/").strip().lstrip("/")
                                if not clean_rf or any(p in clean_rf for p in ["..", "%", "\0", ":"]):
                                    continue
                                parts = clean_rf.split("/")
                                if any(p in ("..", ".", "") or not re.match(r'^[a-zA-Z0-9_.\-]+$', p) for p in parts):
                                    continue
                                if parts[-1] in projects_manager.PROTECTED_FILES or Path(parts[-1]).suffix.lower() not in projects_manager.ALLOWED_GAME_EXTENSIONS:
                                    continue
                                try:
                                    written_rf = projects_manager.write_project_file(user_id_int, safe_slug, clean_rf, rf_content)
                                    if written_rf not in saved_files:
                                        saved_files.append(written_rf)
                                    projects_manager.write_build_log(user_id_int, safe_slug, "REPLACE_CONTENT", f"[REPAIR] Fixed {written_rf}")
                                except Exception:
                                    pass
                        # Re-validate after repair
                        val_result = projects_manager.validate_project(user_id_int, safe_slug)
                except Exception as repair_exc:
                    print(f"[REPAIR] Repair loop bypassed: {repair_exc}")

            # 4. If project is STILL invalid and a pre-build snapshot exists, rollback to protect working state!
            if not val_result.get("valid") and snapshot:
                print(f"[ANTIGRAVITY ROLLBACK] Validation failed after repair ({val_result.get('errors')}). Restoring snapshot.")
                projects_manager.restore_snapshot(user_id_int, safe_slug, snapshot)
                fail_step = f"[FAIL] Validation failed: {val_result.get('errors')}. Restored previous working state."
                projects_manager.write_build_log(user_id_int, safe_slug, "FAIL", fail_step)
                if log_callback:
                    try: await log_callback("fail", fail_step)
                    except Exception: pass
                return {
                    "success": False,
                    "error": f"Build broke project validation ({', '.join(val_result.get('errors', []))}). Restored previous working snapshot.",
                    "rollback_executed": True
                }

            # Verify build
            engine_info = val_result.get("detected_engine", "canvas2d")
            libs_info = f" with {', '.join(val_result.get('libraries', []))}" if val_result.get("libraries") else ""
            verify_step = f"[VERIFY] Syntax & game loop verified across {len(saved_files)} files ({', '.join(saved_files)})"
            projects_manager.write_build_log(user_id_int, safe_slug, "VERIFY", verify_step)
            if log_callback:
                try: await log_callback("verify", verify_step)
                except Exception: pass

            # Update project manifest memory
            manifest_updates = data.get("manifest_updates", {})
            if not isinstance(manifest_updates, dict):
                manifest_updates = {}
            if "engine" not in manifest_updates:
                manifest_updates["engine"] = engine_info
            if val_result.get("libraries"):
                manifest_updates["libraries"] = val_result["libraries"]

            cur_manifest = projects_manager.get_project_manifest(user_id_int, safe_slug)
            manifest_updates["current_build"] = cur_manifest.get("current_build", 1) + 1
            updated_manifest = projects_manager.update_project_manifest(user_id_int, safe_slug, manifest_updates)

            manifest_step = f"[MANIFEST] Architecture memory updated: build #{updated_manifest.get('current_build', 1)} ({updated_manifest.get('engine', 'canvas2d')})"
            projects_manager.write_build_log(user_id_int, safe_slug, "MANIFEST", manifest_step)
            if log_callback:
                try: await log_callback("manifest", manifest_step)
                except Exception: pass

            # Preserve existing project title and tags if present
            existing_proj = await database.get_project(user_id_int, safe_slug)
            existing_title = existing_proj.get("title") if existing_proj else None
            project_title = existing_title or safe_slug.replace("-", " ").title()
            existing_tags = existing_proj.get("tags") if existing_proj else None

            # Update database record
            await database.save_project(
                user_id=user_id_int,
                username=username,
                slug=safe_slug,
                title=project_title,
                description=summary,
                files=saved_files,
                tags=existing_tags
            )

            # Read back ALL project text files so frontend editor tabs retain untouched files!
            all_repo_files = projects_manager.list_project_files(user_id_int, safe_slug)
            full_project_content = {}
            for f in all_repo_files:
                if Path(f).suffix.lower() in text_exts:
                    try:
                        full_project_content[f] = projects_manager.read_project_file(user_id_int, safe_slug, f)
                    except Exception:
                        pass

            pass_step = f"[PASS] Build complete: {summary}"
            projects_manager.write_build_log(user_id_int, safe_slug, "PASS", pass_step)
            if log_callback:
                try: await log_callback("pass", pass_step)
                except Exception: pass

            return {
                "success": True,
                "model_used": used_model,
                "summary": summary,
                "files": saved_files,
                "content": full_project_content,
                "manifest": updated_manifest,
                "validation": val_result,
                "request_id": request_id,
                "build_id": build_id
            }
        except json.JSONDecodeError as jde:
            fail_step = f"[FAIL] Invalid JSON generated: {str(jde)[:80]}"
            projects_manager.write_build_log(user_id_int, safe_slug, "FAIL", fail_step)
            if log_callback:
                try: await log_callback("fail", fail_step)
                except Exception: pass
            return {
                "success": False,
                "error": "Yulya generated invalid formatted code. Please try rephrasing your request."
            }
        except (ValueError, PermissionError) as ve:
            fail_step = f"[FAIL] File security/validation error: {str(ve)}"
            projects_manager.write_build_log(user_id_int, safe_slug, "FAIL", fail_step)
            if log_callback:
                try: await log_callback("fail", fail_step)
                except Exception: pass
            return {
                "success": False,
                "error": f"File validation error: {str(ve)}"
            }
        except Exception as e:
            fail_step = f"[FAIL] Unexpected error: {str(e)[:80]}"
            projects_manager.write_build_log(user_id_int, safe_slug, "FAIL", fail_step)
            if log_callback:
                try: await log_callback("fail", fail_step)
                except Exception: pass
            return {
                "success": False,
                "error": f"Unexpected error processing update: {str(e)}"
            }
