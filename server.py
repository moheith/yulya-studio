import os
import io
import json
import time
import asyncio
import secrets
import base64
from pathlib import Path
from datetime import datetime, timezone
from aiohttp import web, ClientSession
import jinja2
from google import genai
from google.genai import types

import config
import database
import projects_manager
import ai_engine

# In-memory sessions cache: { session_token: { "user": user_dict, "created_at": float } }
SESSION_STORE = {}

# Active WebSocket connections:
# { slug: { "creator": set([ws]), "spectators": set([ws]), "last_seen": { ws: float } } }
ACTIVE_STUDIO_WS = {}

# Active Gemini 3.8 Live Extended Thinking sessions per creator WebSocket:
# { ws: { "session": AsyncSession, "receive_task": asyncio.Task, "slug": str, "client": genai.Client } }
ACTIVE_LIVE_SESSIONS = {}

# Rate limit buckets: { "action:key": [timestamps] }
RATE_LIMIT_BUCKETS = {}

def check_rate_limit(action: str, identifier: str, max_req: int, window_sec: int) -> tuple[bool, int]:
    """
    Sliding window rate limiter (Section 30).
    Returns (is_allowed, seconds_to_wait).
    """
    now = time.time()
    key = f"{action}:{identifier}"
    timestamps = RATE_LIMIT_BUCKETS.get(key, [])
    # Filter out timestamps older than window
    timestamps = [t for t in timestamps if now - t < window_sec]
    
    if len(timestamps) >= max_req:
        oldest = timestamps[0]
        retry_after = int(window_sec - (now - oldest)) + 1
        RATE_LIMIT_BUCKETS[key] = timestamps
        return False, max(1, retry_after)
        
    timestamps.append(now)
    RATE_LIMIT_BUCKETS[key] = timestamps
    return True, 0

async def get_session_user(request: web.Request) -> dict | None:
    token = request.cookies.get(config.COOKIE_NAME) or request.query.get("token")
    if not token:
        return None
    if token in SESSION_STORE:
        return SESSION_STORE[token].get("user")
    
    # Check MongoDB sessions
    doc = await database.get_session(token)
    if doc:
        SESSION_STORE[token] = doc
        return doc.get("user")
    return None

async def set_session_user(response: web.Response, user_data: dict) -> str:
    token = secrets.token_urlsafe(32)
    session_payload = {
        "token": token,
        "user": user_data,
        "created_at": time.time()
    }
    SESSION_STORE[token] = session_payload
    await database.save_session(token, user_data)
    
    response.set_cookie(
        config.COOKIE_NAME,
        token,
        max_age=86400 * 30, # 30 days
        httponly=True,
        samesite="Lax",
        secure=config.COOKIE_SECURE,
        path="/"
    )
    return token

async def render_template(template_name: str, context: dict = None) -> web.Response:
    context = context or {}
    template_path = config.TEMPLATES_DIR / template_name
    template_content = template_path.read_text(encoding="utf-8")
    env = jinja2.Environment(autoescape=True)
    template = env.from_string(template_content)
    rendered = template.render(**context)
    return web.Response(text=rendered, content_type="text/html")

# --- Security Middlewares ---

@web.middleware
async def security_headers_middleware(request, handler):
    # CSRF Check for state-changing POST requests (Section 29)
    if request.method in ["POST", "PUT", "DELETE"]:
        origin = request.headers.get("Origin") or request.headers.get("Referer")
        if origin:
            expected_host = request.host.lower()
            # If origin has scheme, check domain
            origin_clean = origin.split("://")[-1].split("/")[0].lower()
            if origin_clean != expected_host and not origin_clean.endswith(".onrender.com") and not origin_clean.endswith("yulya.me"):
                return web.json_response({
                    "success": False,
                    "error": "This request could not be verified (CSRF mismatch). Please refresh the page and try again."
                }, status=403)
                
    response = await handler(request)
    
    # CSP & Defense in depth headers (Section 33)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    
    # CSP tailored to support WebSockets, Google Fonts, and sandboxed preview iframes
    csp_policy = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "frame-src 'self'; "
        "connect-src 'self' wss: ws: https:; "
        "img-src 'self' data: https:;"
    )
    response.headers["Content-Security-Policy"] = csp_policy
    return response

# --- Page Handlers ---

async def handle_index(request: web.Request) -> web.Response:
    """Public Arcade Gallery Homepage"""
    user = await get_session_user(request)
    games = await database.list_community_arcade(limit=50)
    return await render_template("index.html", {"user": user, "games": games})

async def handle_studio(request: web.Request) -> web.Response:
    """Creator Studio Workspace or Profile Redirect"""
    user = await get_session_user(request)
    
    if not user:
        return await render_template("onboarding.html", {"user": None})
        
    profile = await database.get_user_profile(user["id"])
    has_api_key = profile and profile.get("studio_api_key")
    
    if not has_api_key:
        return await render_template("onboarding.html", {"user": user})
        
    slug = request.query.get("slug")
    
    # If a specific project slug is requested:
    if slug:
        proj = await database.get_project(user["id"], slug)
        if not proj:
            proj = await database.get_project_by_username_and_slug(user["username"], slug)
        if proj:
            projects = await database.list_user_projects(user["id"])
            return await render_template("studio.html", {
                "user": user,
                "projects": projects,
                "active_slug": slug,
                "active_project": proj,
                "spectator_token": proj.get("spectator_token", "")
            })
            
    # Never auto-create games! Cleanly redirect to the user's profile where they can browse and click "+ New Project"
    return web.HTTPFound(f"/{user['username']}")

async def handle_spectate(request: web.Request) -> web.Response:
    """
    Spectator HUD for live session streaming.
    Supports either /spectate/{username}/{slug} or /spectate/{token} (Section 107).
    """
    token = request.match_info.get("token")
    username = request.match_info.get("username")
    slug = request.match_info.get("slug")
    
    proj = None
    if token:
        proj = await database.get_project_by_spectator_token(token)
    elif username and slug:
        proj = await database.get_project_by_username_and_slug(username, slug)
        
    if not proj:
        return web.Response(text="Spectator session or project not found.", status=404)
        
    return await render_template("spectator.html", {
        "author": proj.get("username", "creator"),
        "slug": proj.get("slug", "game"),
        "title": proj.get("title", proj.get("slug", "Game")),
        "spectator_token": proj.get("spectator_token", "")
    })

# --- Discord OAuth Routes (Section 78) ---

async def handle_login(request: web.Request) -> web.Response:
    return web.HTTPFound(config.DISCORD_OAUTH_URL)

async def handle_auth_callback(request: web.Request) -> web.Response:
    code = request.query.get("code")
    if not code:
        return web.HTTPFound("/")
        
    data = {
        "client_id": config.DISCORD_CLIENT_ID,
        "client_secret": config.DISCORD_CLIENT_SECRET,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": f"{config.BASE_URL}/auth/callback"
    }
    
    try:
        async with ClientSession() as client:
            async with client.post("https://discord.com/api/oauth2/token", data=data) as token_resp:
                token_data = await token_resp.json()
                access_token = token_data.get("access_token")
                
            if not access_token:
                return web.HTTPFound("/studio")
                
            headers = {"Authorization": f"Bearer {access_token}"}
            async with client.get("https://discord.com/api/users/@me", headers=headers) as user_resp:
                user_data = await user_resp.json()
                
        if "id" in user_data:
            user_info = {
                "id": int(user_data["id"]),
                "username": user_data["username"],
                "display_name": user_data.get("global_name") or user_data["username"],
                "avatar": user_data.get("avatar")
            }
            # Save or update dedicated studio_profiles document
            try:
                await database.save_or_update_profile(
                    user_id=user_info["id"],
                    username=user_info["username"],
                    display_name=user_info["display_name"],
                    avatar=user_info["avatar"]
                )
            except Exception as e:
                print(f"[AUTH] Error updating studio profile: {e}")
                
            # If user already has an API key configured, route directly to their public profile
            profile = await database.get_user_profile(user_info["id"])
            if profile and profile.get("studio_api_key"):
                response = web.HTTPFound(f"/{user_info['username']}")
            else:
                response = web.HTTPFound("/studio")
                
            await set_session_user(response, user_info)
            return response
        return web.HTTPFound("/studio")
    except Exception as e:
        print(f"[AUTH] OAuth error: {e}")
        return web.HTTPFound("/studio")

async def handle_logout(request: web.Request) -> web.Response:
    token = request.cookies.get(config.COOKIE_NAME)
    if token:
        if token in SESSION_STORE:
            del SESSION_STORE[token]
        await database.delete_session(token)
        
    response = web.HTTPFound("/")
    response.del_cookie(config.COOKIE_NAME, path="/")
    return response

# --- REST API Endpoints (Section 18) ---

async def api_save_key(request: web.Request) -> web.Response:
    user = await get_session_user(request)
    if not user:
        return web.json_response({"success": False, "error": "Your session has expired. Please sign in again."}, status=401)
        
    # Rate limit: 5 requests / min (Section 30)
    allowed, wait_sec = check_rate_limit("save_key", str(user["id"]), *config.RATE_LIMIT_SAVE_KEY)
    if not allowed:
        return web.json_response({
            "success": False, 
            "error": f"You're sending requests too quickly. Try again in {wait_sec} seconds."
        }, status=429)
        
    try:
        body = await request.json()
        key = body.get("api_key", "").strip()
        res = await database.save_user_api_key(user["id"], key, user["username"])
        if res.get("success"):
            res["redirect_url"] = f"/{user['username']}"
        status_code = 200 if res.get("success") else 400
        return web.json_response(res, status=status_code)
    except Exception as e:
        return web.json_response({"success": False, "error": f"Failed to save key: {str(e)}"}, status=400)

async def api_create_project(request: web.Request) -> web.Response:
    user = await get_session_user(request)
    if not user:
        return web.json_response({"success": False, "error": "Your session has expired. Please sign in again."}, status=401)
        
    # Rate limit: 5 requests / min (Section 30)
    allowed, wait_sec = check_rate_limit("create_proj", str(user["id"]), *config.RATE_LIMIT_CREATE)
    if not allowed:
        return web.json_response({
            "success": False, 
            "error": f"You're creating projects too quickly. Try again in {wait_sec} seconds."
        }, status=429)
        
    try:
        body = await request.json()
        title = body.get("title", "New Game").strip()
        if not title:
            title = "New Game"
            
        slug = title.lower().replace(" ", "-")
        slug = "".join(c for c in slug if c.isalnum() or c in "-_").strip("-")
        if not slug:
            slug = "game"
            
        existing = await database.get_project(user["id"], slug)
        if existing:
            slug = f"{slug}-{secrets.token_hex(2)}"
            
        projects_manager.create_starter_game(user["id"], user["username"], slug, title)
        proj_doc = await database.save_project(
            user_id=user["id"],
            username=user["username"],
            slug=slug,
            title=title,
            description=f"A new web game by {user['username']}."
        )
        return web.json_response({
            "success": True, 
            "slug": slug, 
            "title": title,
            "spectator_token": proj_doc.get("spectator_token")
        })
    except Exception as e:
        return web.json_response({"success": False, "error": f"Project creation failed: {str(e)}"}, status=400)

async def api_modify_project(request: web.Request) -> web.Response:
    user = await get_session_user(request)
    if not user:
        return web.json_response({"success": False, "error": "Your session has expired. Please sign in again."}, status=401)
        
    # Rate limit: 10 requests / min (Section 30)
    allowed, wait_sec = check_rate_limit("modify_proj", str(user["id"]), *config.RATE_LIMIT_MODIFY)
    if not allowed:
        return web.json_response({
            "success": False, 
            "error": f"You're sending requests too quickly. Try again in {wait_sec} seconds."
        }, status=429)
        
    try:
        body = await request.json()
        slug = body.get("slug")
        prompt = body.get("prompt", "").strip()
        
        if not slug or not prompt:
            return web.json_response({"success": False, "error": "Missing slug or prompt."}, status=400)
            
        # Ownership check (Section 79)
        proj = await database.get_project(user["id"], slug)
        if not proj:
            return web.json_response({"success": False, "error": "Project not found or not owned by you."}, status=404)
            
        profile = await database.get_user_profile(user["id"])
        api_key = profile.get("studio_api_key") if profile else None
        if not api_key:
            return web.json_response({"success": False, "error": "No Google AI Studio API key saved. Please set up your key first."}, status=400)
            
        # Broadcast Antigravity CLI log steps to connected WebSockets
        async def _log_callback(step_type, message_text):
            await broadcast_project_log(slug, message_text, step_type)
            
        result = await ai_engine.process_code_request(
            api_key, user["id"], user["username"], slug, prompt, log_callback=_log_callback
        )
        
        if result.get("success"):
            # Hot-reload update to creator + spectators (Section 20)
            await broadcast_project_update(slug, {
                "type": "code_update",
                "summary": result["summary"],
                "content": result["content"],
                "timestamp": int(time.time())
            })
            for live_ws, live_info in list(ACTIVE_LIVE_SESSIONS.items()):
                if live_info.get("slug") == slug and not live_ws.closed:
                    try:
                        s = live_info.get("session")
                        if s:
                            await s.send(
                                input=(
                                    f"[System: Antigravity has completed compiling the game: '{result['summary']}'. "
                                    "The game is now running in the preview iframe on screen! "
                                    "Tell the creator that their build is complete! Invite them to test playing it, "
                                    "and remind them they can click the Screenshare button so you can watch them play live, "
                                    "see how the game feels, and brainstorm next improvements together.]"
                                ),
                                end_of_turn=True
                            )
                    except Exception:
                        pass
            
        return web.json_response(result)
    except Exception as e:
        return web.json_response({"success": False, "error": f"Error modifying project: {str(e)}"}, status=500)

async def api_delete_project(request: web.Request) -> web.Response:
    """Deletes a project safely (Section 74)"""
    user = await get_session_user(request)
    if not user:
        return web.json_response({"success": False, "error": "Unauthorized."}, status=401)
        
    try:
        body = await request.json()
        slug = body.get("slug")
        if not slug:
            return web.json_response({"success": False, "error": "Missing slug."}, status=400)
            
        # Verify ownership
        proj = await database.get_project(user["id"], slug)
        if not proj:
            return web.json_response({"success": False, "error": "Project not found or not owned by you."}, status=404)
            
        # Remove files safely
        projects_manager.delete_project_dir(user["id"], slug)
        # Remove database entry
        await database.delete_project(user["id"], slug)
        
        return web.json_response({"success": True, "message": f"Project '{slug}' deleted."})
    except Exception as e:
        return web.json_response({"success": False, "error": f"Failed to delete: {str(e)}"}, status=400)

async def api_leave_vc(request: web.Request) -> web.Response:
    """Signals the Discord Bot to gracefully leave VC (Section 108)"""
    user = await get_session_user(request)
    if not user:
        return web.json_response({"success": False, "error": "Not authenticated."}, status=401)
        
    # Write leave signal to shared MongoDB collection
    await database.send_studio_signal("leave_vc", user["id"], {"username": user["username"]})
    return web.json_response({"success": True, "message": "Leave VC signal dispatched to Discord bot."})

async def api_project_files(request: web.Request) -> web.Response:
    """Returns all project code files for the active editor or spectator (Section 18 & 97)"""
    slug = request.match_info["slug"].lower()
    token = request.query.get("token")
    user = await get_session_user(request)
    
    proj = None
    if user:
        proj = await database.get_project(user["id"], slug)
        
    if not proj and token:
        proj = await database.get_project_by_spectator_token(token)
        
    if not proj:
        author = request.query.get("author")
        if author:
            proj = await database.get_project_by_username_and_slug(author, slug)
        elif database.projects_col is not None:
            proj = await database.projects_col.find_one({"slug": slug, "is_public": {"$ne": False}})
            
    if not proj:
        return web.json_response({"success": False, "error": "Project not found or access denied."}, status=404)
        
    files = projects_manager.get_project_all_files(proj["user_id"], slug)
    return web.json_response({"success": True, "slug": slug, "files": files})

async def api_community_projects(request: web.Request) -> web.Response:
    """Arcade community showcase projects"""
    projects = await database.list_community_arcade(limit=50)
    # Strip any sensitive database internal fields before returning
    clean = []
    for p in projects:
        clean.append({
            "id": p.get("_id"),
            "slug": p.get("slug"),
            "title": p.get("title") or p.get("slug"),
            "username": p.get("username"),
            "description": p.get("description"),
            "tags": p.get("tags", []),
            "spectator_token": p.get("spectator_token", "")
        })
    return web.json_response(clean)

async def api_download_zip(request: web.Request) -> web.Response:
    """ZIP export of full project code (Section 75)"""
    username = request.match_info["username"].lower()
    slug = request.match_info["slug"].lower()
    
    proj = await database.get_project_by_username_and_slug(username, slug)
    if not proj:
        return web.Response(text="Project not found", status=404)
        
    zip_buf = projects_manager.create_zip_archive(proj["user_id"], slug)
    return web.Response(
        body=zip_buf.read(),
        content_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{slug}.zip"'}
    )

# --- Static Game Hosting: /{username}/{slug}/* (Section 71) ---

async def handle_game_redirect(request: web.Request) -> web.Response:
    """Redirects /{username}/{slug} to /{username}/{slug}/ so relative assets resolve correctly."""
    username = request.match_info["username"]
    slug = request.match_info["slug"]
    qs = f"?{request.query_string}" if request.query_string else ""
    raise web.HTTPFound(f"/{username}/{slug}/{qs}")

async def handle_game_asset(request: web.Request) -> web.Response:
    username = request.match_info["username"].lower()
    slug = request.match_info["slug"].lower()
    filename = request.match_info.get("file", "index.html")
    if not filename:
        filename = "index.html"
        
    proj = await database.get_project_by_username_and_slug(username, slug)
    if not proj:
        return web.Response(text="Game not found", status=404)
        
    # Strictly validate filename to prevent path traversal
    safe_name = os.path.basename(filename)
    if not safe_name or ".." in safe_name or "/" in filename or "\\" in filename:
        safe_name = "index.html"
        
    # Block protected files, build logs, hidden files, and disallowed extensions
    if safe_name.startswith(".") or safe_name in projects_manager.PROTECTED_FILES:
        return web.Response(text="Access denied", status=403)

    ext = Path(safe_name).suffix.lower()
    if ext in projects_manager.DISALLOWED_EXTENSIONS:
        return web.Response(text="Access denied", status=403)
        
    pdir = projects_manager.get_user_project_dir(proj["user_id"], slug).resolve()
    target = (pdir / safe_name).resolve()
    
    try:
        target.relative_to(pdir)
    except ValueError:
        return web.Response(text="Access denied", status=403)
        
    if target.is_symlink() or os.path.islink(str(target)):
        return web.Response(text="Access denied: symlinks forbidden", status=403)
        
    if not target.exists() or not target.is_file():
        return web.Response(text="File not found", status=404)
        
    content_type = "text/html"
    charset = "utf-8"
    if safe_name.endswith(".css"): content_type = "text/css"
    elif safe_name.endswith(".js"): content_type = "application/javascript"
    elif safe_name.endswith(".json"): content_type = "application/json"
    elif safe_name.endswith(".png"): content_type = "image/png"; charset = None
    elif safe_name.endswith((".jpg", ".jpeg")): content_type = "image/jpeg"; charset = None
    elif safe_name.endswith(".svg"): content_type = "image/svg+xml"; charset = "utf-8"
    
    body_bytes = target.read_bytes()
    is_iframe = (request.headers.get("Sec-Fetch-Dest") == "iframe") or (request.query.get("embed") == "1") or (request.query.get("raw") == "1")
    
    # If viewed directly in browser by owner, inject sleek "Edit in Studio" button
    if safe_name == "index.html" and not is_iframe:
        session_user = await get_session_user(request)
        is_owner = (session_user is not None and (session_user.get("id") == proj.get("user_id") or session_user.get("username", "").lower() == username))
        
        if is_owner:
            banner = f"""<div style="position:fixed;top:14px;right:14px;z-index:999999;display:flex;align-items:center;gap:10px;background:rgba(10,5,24,0.92);backdrop-filter:blur(10px);border:1px solid rgba(139,92,246,0.35);padding:6px 14px;border-radius:24px;font-family:-apple-system,BlinkMacSystemFont,sans-serif;font-size:12px;box-shadow:0 6px 20px rgba(0,0,0,0.6);"><a href="/{username}" style="color:#9590a8;text-decoration:none;font-weight:500;">@{username}</a><span style="color:rgba(255,255,255,0.2);">|</span><a href="/{username}/{slug}/studio" style="color:#a78bfa;font-weight:600;text-decoration:none;display:flex;align-items:center;gap:4px;">Edit in Studio &rarr;</a></div>"""
        else:
            banner = f"""<div style="position:fixed;top:14px;right:14px;z-index:999999;display:flex;align-items:center;gap:10px;background:rgba(10,5,24,0.88);backdrop-filter:blur(10px);border:1px solid rgba(255,255,255,0.12);padding:6px 14px;border-radius:24px;font-family:-apple-system,BlinkMacSystemFont,sans-serif;font-size:12px;box-shadow:0 6px 20px rgba(0,0,0,0.6);"><a href="/{username}" style="color:#38bdf8;font-weight:600;text-decoration:none;">@{username}'s Profile &rarr;</a></div>"""
            
        html_str = body_bytes.decode("utf-8", errors="replace")
        if "</body>" in html_str:
            html_str = html_str.replace("</body>", f"{banner}</body>")
        else:
            html_str += banner
        body_bytes = html_str.encode("utf-8")
        
    return web.Response(
        body=body_bytes,
        content_type=content_type,
        charset=charset,
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate",
            "X-Content-Type-Options": "nosniff"
        }
    )

# --- GitHub-Style Portfolio & Studio Repository Handlers (Section 1) ---

RESERVED_USERNAMES = {"static", "api", "auth", "ws", "studio", "spectate", "favicon.ico"}

async def handle_user_profile(request: web.Request) -> web.Response:
    """User profile / portfolio page at /{username} (Section 1)"""
    username = request.match_info["username"]
    clean_username = username.strip().lower()
    
    if clean_username in RESERVED_USERNAMES:
        return web.Response(text="Not found", status=404)
        
    session_user = await get_session_user(request)
    profile = await database.get_profile_by_username(clean_username)
    
    if not profile:
        # Check if logged in user is viewing their own profile
        if session_user and session_user.get("username", "").lower() == clean_username:
            profile = await database.save_or_update_profile(
                user_id=session_user["id"],
                username=clean_username,
                display_name=session_user.get("display_name") or clean_username,
                avatar=session_user.get("avatar")
            )
            
    if not profile:
        return web.Response(text=f"User @{username} not found.", status=404)
        
    is_owner = (session_user is not None and (session_user.get("id") == profile.get("user_id") or session_user.get("username", "").lower() == clean_username))
    
    games = profile.get("created_games", [])
    if not games and database.projects_col is not None:
        user_projects = await database.list_user_projects(profile.get("user_id", 0))
        if user_projects:
            games = [
                {
                    "slug": p.get("slug"),
                    "title": p.get("title") or p.get("slug"),
                    "description": p.get("description", ""),
                    "tags": p.get("tags", []),
                    "created_at": str(p.get("created_at", "")),
                    "updated_at": str(p.get("updated_at", ""))
                }
                for p in user_projects
            ]
            
    return await render_template("profile.html", {
        "user": session_user,
        "profile": profile,
        "is_owner": is_owner,
        "games": games
    })

async def handle_user_slug_studio(request: web.Request) -> web.Response:
    """Creator IDE dual-pane workspace at /{username}/{slug}/studio"""
    username = request.match_info["username"].lower()
    slug = request.match_info["slug"].lower()
    
    session_user = await get_session_user(request)
    if not session_user:
        return web.HTTPFound(f"/auth/login")
        
    proj = await database.get_project_by_username_and_slug(username, slug)
    if not proj:
        return web.Response(text="Project not found", status=404)
        
    # Check if user is owner
    if session_user["id"] != proj["user_id"] and session_user.get("username", "").lower() != username:
        # Not owner, redirect to spectate
        return web.HTTPFound(f"/spectate/{username}/{slug}")
        
    # Redirect to studio with active slug
    return web.HTTPFound(f"/studio?slug={slug}")

async def api_project_logs(request: web.Request) -> web.Response:
    """Returns Antigravity CLI activity log entries from build.log (Section 4)"""
    slug = request.match_info["slug"].lower()
    token = request.query.get("token")
    user = await get_session_user(request)
    
    proj = None
    if user:
        proj = await database.get_project(user["id"], slug)
    if not proj and token:
        proj = await database.get_project_by_spectator_token(token)
    if not proj:
        author = request.query.get("author")
        if author:
            proj = await database.get_project_by_username_and_slug(author, slug)
        elif database.projects_col is not None:
            proj = await database.projects_col.find_one({"slug": slug, "is_public": {"$ne": False}})
            
    if not proj:
        return web.json_response({"success": False, "error": "Project not found."}, status=404)
        
    logs = projects_manager.read_build_log(proj["user_id"], slug, max_lines=200)
    return web.json_response({"success": True, "slug": slug, "logs": logs})

async def api_save_project_log(request: web.Request) -> web.Response:
    """Appends an activity or session log entry to build.log (e.g. exit/close events)"""
    slug = request.match_info["slug"].lower()
    user = await get_session_user(request)
    if not user:
        return web.json_response({"success": False, "error": "Unauthorized."}, status=401)
        
    proj = await database.get_project(user["id"], slug)
    if not proj:
        return web.json_response({"success": False, "error": "Project not found."}, status=404)
        
    try:
        data = await request.json()
        step = str(data.get("step", "INFO")).upper()[:20]
        msg = str(data.get("message", "Session event"))[:200]
        projects_manager.write_build_log(user["id"], slug, step, msg)
        return web.json_response({"success": True})
    except Exception as e:
        return web.json_response({"success": False, "error": str(e)}, status=400)

# --- Gemini 3.8 Live Multimodal Session Bridge ---

async def start_gemini_live_session(ws: web.WebSocketResponse, slug: str, session_user: dict):
    """
    Initializes a bi-directional Gemini 3.8 Live session using the user's personal API key.
    Configured strictly for Gemini 3.8 Live Extended Thinking on High without waterfall.
    """
    try:
        user_id = session_user["id"]
        username = session_user["username"]
        profile = await database.get_user_profile(user_id)
        api_key = profile.get("studio_api_key") if profile else None
        if not api_key:
            st_prof = await database.get_profile_by_user_id(user_id)
            if st_prof and st_prof.get("studio_api_key"):
                api_key = st_prof.get("studio_api_key")
        
        if not api_key:
            if not ws.closed:
                await ws.send_json({
                    "type": "live_error",
                    "message": "Google AI Studio API key not found in profile. Please add your key in your profile."
                })
            await broadcast_project_log(slug, "[LIVE_ERROR] Google AI Studio API key not found. Please save your key in your profile.", "error")
            return

        # Close existing session for this socket if any
        await stop_gemini_live_session(ws)

        # Notify UI that connection handshake is active
        if not ws.closed:
            await ws.send_json({
                "type": "live_status",
                "status": "connecting",
                "message": "Connecting to Gemini 3.8 Live Extended Thinking (High)..."
            })
        await broadcast_project_log(slug, "[LIVE] Connecting to Gemini 3.8 Live Extended Thinking (High)...", "live")

        # Read existing project files for immediate context
        index_html = projects_manager.read_project_file(user_id, slug, "index.html")
        style_css = projects_manager.read_project_file(user_id, slug, "style.css")
        app_js = projects_manager.read_project_file(user_id, slug, "app.js")

        live_sys_prompt = f"""You are Gemini 3.8 Live Extended Thinking on High, an interactive AI Game Architect and Pair-Programming Co-pilot inside Yulya Studio.
Your thinking mode is set to Extended Thinking on High. You are having an ongoing real-time voice call with the creator @{session_user.get('username', 'creator')} building an HTML5 Canvas web game named '{slug}'.

WORKFLOW & DESIGN GUIDELINES:

1. THE "GRILL ME" INTERACTIVE DESIGN INTERVIEW:
- When the creator describes an idea, DO NOT build immediately.
- "Grill" the creator with smart, creative, and specific questions to thoroughly flesh out the game.
- Ask about:
  * Core gameplay mechanics, win/loss rules, and scoring
  * Art style and visual aesthetic (always provide 2-3 clear options to choose from, e.g. Neon Cyberpunk vs Retro 8-bit Pixel vs Minimalist Pastel)
  * Control scheme (e.g. Arrow keys, WASD, Mouse aim, Mobile touch)
  * Enemy types, difficulty progression, hazards, and power-ups
- Ask 1 or 2 focused questions at a time with concrete options so the creator can easily reply.
- Dig into the details until you have a complete, polished game plan.

2. DRAFTING THE PROMPT & ASKING PERMISSION (MANDATORY BEFORE BUILDING):
- When you and the creator have fleshed out the entire idea and are ready to build:
  * Ask the creator if they would like you to draft the build prompt for Antigravity.
  * Call your tool `draft_prompt_to_input(prompt=...)` with the comprehensive, detailed engineering specification you designed.
  * Tell the creator: "I've drafted the complete build prompt in your command box at the bottom of the screen! You can review it, edit it if you want, and press Enter to send it — or just say 'send it' and I'll send it directly to Antigravity for you."
  * If the creator asks "Can you read the prompt to me?", read the full prompt aloud in your voice and ask for their confirmation!

3. SENDING TO ANTIGRAVITY CODING ENGINE:
- When the creator confirms verbally ("send it", "just send it", "go ahead and build", "yes build it"):
  * Call your tool `send_prompt_to_antigravity(instruction=...)`.
  * Tell the creator you sent it to Antigravity and it's compiling now!
- (Note: The creator may also press Enter on the command box themselves to launch it.)

4. CHATTING WHILE BUILDING (NON-BLOCKING):
- While Antigravity is compiling code in the background, you and the creator can continue talking freely!
- Brainstorm extra features, power-ups, audio ideas, visual effects, or future ideas to add once the build finishes.

5. TESTING, SCREENSHARING & ITERATIVE POLISH:
- When Antigravity completes the build, you will receive a notification.
- Congratulate the creator and invite them to test playing the game right in the live preview window!
- Encourage them to click the "Screenshare" button so you can watch their screen live.
- When they screenshare and play, observe their canvas, critique how it feels and looks, and discuss improvements.
- When they want to add new features or fixes, repeat the process: draft the new prompt into their input box with `draft_prompt_to_input`, ask permission, and build!

TOOLS:
- `draft_prompt_to_input(prompt: str)`: Populates the creator's on-screen input box with the drafted Antigravity build prompt.
- `send_prompt_to_antigravity(instruction: str)`: Hands off the approved instruction to Antigravity to build/compile the game.

Keep your spoken voice responses conversational, energetic, clear, and natural. Keep spoken sentences punchy and engaging.

Current Game Repository Files:
--- index.html ---
{index_html[:6000]}
--- style.css ---
{style_css[:4000]}
--- app.js ---
{app_js[:8000]}
"""

        architect_tools = types.Tool(
            function_declarations=[
                types.FunctionDeclaration(
                    name="draft_prompt_to_input",
                    description="Populates the drafted Antigravity engineering prompt into the creator's on-screen command input text box for review and editing before sending.",
                    parameters=types.Schema(
                        type="OBJECT",
                        properties={
                            "prompt": types.Schema(type="STRING", description="The complete, detailed engineering specification prompt for Antigravity.")
                        },
                        required=["prompt"]
                    )
                ),
                types.FunctionDeclaration(
                    name="send_prompt_to_antigravity",
                    description="Sends the approved build instruction to the Antigravity Coding Engine to compile and update the game files.",
                    parameters=types.Schema(
                        type="OBJECT",
                        properties={
                            "instruction": types.Schema(type="STRING", description="Detailed code modification instruction to build.")
                        },
                        required=["instruction"]
                    )
                ),
                types.FunctionDeclaration(
                    name="modify_game_code",
                    description="Builds or modifies HTML5 Canvas game files with Antigravity.",
                    parameters=types.Schema(
                        type="OBJECT",
                        properties={
                            "instruction": types.Schema(type="STRING", description="Detailed code modification instruction")
                        },
                        required=["instruction"]
                    )
                )
            ]
        )

        client = genai.Client(api_key=api_key.strip())
        connected_model = "Gemini 3.8 Live Extended Thinking (High)"
        live_model = "gemini-3.8-live"

        live_cm = client.aio.live.connect(
            model=live_model,
            config={
                "response_modalities": ["AUDIO"],
                "system_instruction": types.Content(parts=[types.Part.from_text(text=live_sys_prompt)]),
                "tools": [architect_tools],
                "generation_config": {
                    "thinking_config": {
                        "include_thoughts": True
                    }
                }
            }
        )
        session = await live_cm.__aenter__()

        # Start receive loop task
        receive_task = asyncio.create_task(_live_receive_loop(ws, slug, session, api_key, session_user))
        ACTIVE_LIVE_SESSIONS[ws] = {
            "session": session,
            "cm": live_cm,
            "receive_task": receive_task,
            "slug": slug,
            "client": client
        }

        if not ws.closed:
            await ws.send_json({
                "type": "live_status",
                "status": "connected",
                "model": connected_model
            })
        await broadcast_project_log(slug, f"[LIVE] Connected to {connected_model}", "live")

        # Greet user first and start the 'grill-me' project interview immediately
        try:
            creator_name = session_user.get("username", "creator")
            await session.send(
                input=(
                    f"The creator @{creator_name} has just joined the call for the HTML5 Canvas project '{slug}'. "
                    "Speak immediately right now in voice: Greet @{creator_name} warmly and with high energy! "
                    "Introduce yourself as their AI Game Architect & pair-programming co-pilot in Yulya Studio. "
                    "Ask them what game or project idea they want to create today, and begin the design interview to help them plan and architect it!"
                ),
                end_of_turn=True
            )
        except Exception as greet_err:
            print(f"[LIVE GREET ERROR] {greet_err}")

    except Exception as e:
        print(f"[LIVE ERROR] start_gemini_live_session: {e}")
        err_msg = str(e)
        if not ws.closed:
            await ws.send_json({
                "type": "live_error",
                "message": f"Gemini 3.8 Live error: {err_msg[:120]}"
            })
        await broadcast_project_log(slug, f"[LIVE_ERROR] {err_msg[:140]}", "error")

async def _run_antigravity_builder(slug: str, session_user: dict, api_key: str, instruction: str, ws: web.WebSocketResponse, session=None):
    """
    Executes Antigravity code generation in a background task so the Gemini Live voice call
    and receive loop stay unblocked. Creator can continue speaking with Gemini Live while coding runs.
    """
    try:
        if not ws.closed:
            await ws.send_json({"type": "show_loader", "text": f"Antigravity is coding: {instruction[:60]}..."})

        async def _cb(step_type, msg_text):
            await broadcast_project_log(slug, msg_text, step_type)

        res = await ai_engine.process_code_request(
            api_key, session_user["id"], session_user["username"], slug, instruction, log_callback=_cb
        )

        if not ws.closed:
            await ws.send_json({"type": "hide_loader"})

        if res.get("success"):
            await broadcast_project_update(slug, {
                "type": "code_update",
                "summary": res["summary"],
                "content": res["content"],
                "timestamp": int(time.time())
            })
            await broadcast_project_log(slug, f"[PASS] {res['summary']}", "pass")

            # Notify Gemini Live voice session that build is complete and ready for playtesting / screenshare
            if session and not ws.closed and ws in ACTIVE_LIVE_SESSIONS:
                try:
                    await session.send(
                        input=(
                            f"[System: Antigravity has completed compiling the game: '{res['summary']}'. "
                            "The game is now running in the preview iframe on screen! "
                            "Tell the creator that the build finished successfully! Invite them to test playing it right now in the preview, "
                            "and remind them they can click the Screenshare button so you can watch them play live, "
                            "see how the game feels, and brainstorm next improvements together.]"
                        ),
                        end_of_turn=True
                    )
                except Exception as notify_err:
                    print(f"[LIVE POST-BUILD NOTIFY ERROR] {notify_err}")
        else:
            err_msg = res.get("error", "Code build failed")
            await broadcast_project_log(slug, f"[FAIL] Antigravity build failed: {err_msg}", "fail")
            if session and not ws.closed and ws in ACTIVE_LIVE_SESSIONS:
                try:
                    await session.send(
                        input=f"[System: Antigravity build failed: {err_msg}. Inform the creator and discuss how to adjust the plan.]",
                        end_of_turn=True
                    )
                except Exception:
                    pass
    except Exception as e:
        print(f"[ANTIGRAVITY BUILDER ERROR] {e}")
        await broadcast_project_log(slug, f"[FAIL] Antigravity error: {e}", "fail")
        if not ws.closed:
            try:
                await ws.send_json({"type": "hide_loader"})
            except Exception:
                pass

async def _live_receive_loop(ws: web.WebSocketResponse, slug: str, session, api_key: str, session_user: dict):
    """Background listener for streaming audio, thoughts, and tool calls from Gemini Live across all turns."""
    try:
        while not ws.closed and ws in ACTIVE_LIVE_SESSIONS:
            try:
                async for response in session.receive():
                    if ws.closed or ws not in ACTIVE_LIVE_SESSIONS:
                        break
                        
                    server_content = response.server_content
                    if server_content:
                        model_turn = server_content.model_turn
                        if model_turn:
                            for part in model_turn.parts:
                                # PCM Audio response (24kHz little-endian)
                                if part.inline_data and part.inline_data.data:
                                    raw_data = part.inline_data.data
                                    if isinstance(raw_data, bytes):
                                        audio_b64 = base64.b64encode(raw_data).decode("ascii")
                                    elif isinstance(raw_data, str):
                                        try:
                                            base64.b64decode(raw_data)
                                            audio_b64 = raw_data
                                        except Exception:
                                            audio_b64 = base64.b64encode(raw_data.encode("utf-8")).decode("ascii")
                                    else:
                                        audio_b64 = ""
                                    if audio_b64 and not ws.closed:
                                        await ws.send_json({
                                            "type": "ai_audio",
                                            "pcm": audio_b64,
                                            "rate": 24000
                                        })
                                # Extended Thinking thoughts
                                if getattr(part, "thought", None):
                                    thought_text = str(part.thought).strip()
                                    if thought_text:
                                        await broadcast_project_log(slug, f"[THINKING] {thought_text}", "thinking")
                                if part.text:
                                    if not ws.closed:
                                        await ws.send_json({
                                            "type": "ai_text",
                                            "text": part.text
                                        })
                                        
                        if server_content.turn_complete:
                            if not ws.closed:
                                await ws.send_json({"type": "ai_turn_complete"})
                        if getattr(server_content, "interrupted", False):
                            if not ws.closed:
                                await ws.send_json({"type": "ai_interrupted"})

                    # Handle tool calls (Architect invoking Antigravity tools)
                    tool_call = response.tool_call
                    if tool_call and tool_call.function_calls:
                        for fc in tool_call.function_calls:
                            if fc.name == "draft_prompt_to_input":
                                drafted_prompt = fc.args.get("prompt", "").strip()
                                await broadcast_project_log(slug, f"[ARCHITECT] Drafted prompt to command box: \"{drafted_prompt[:80]}...\"", "info")
                                if not ws.closed:
                                    await ws.send_json({
                                        "type": "set_command_input",
                                        "text": drafted_prompt
                                    })

                                tool_resp = types.LiveClientToolResponse(
                                    function_responses=[
                                        types.FunctionResponse(
                                            name="draft_prompt_to_input",
                                            id=fc.id,
                                            response={
                                                "result": (
                                                    "The prompt has been placed into the creator's command input box on screen. "
                                                    "Tell the creator you have placed the prompt into their input box at the bottom of the screen. "
                                                    "Let them know they can review it, edit it, and press Enter to send it — or they can just say 'send it' and you will send it to Antigravity. "
                                                    "Also offer to read the prompt aloud if they want you to read it."
                                                )
                                            }
                                        )
                                    ]
                                )
                                try:
                                    await session.send(input=tool_resp)
                                except Exception as e:
                                    print(f"[LIVE TOOL SEND ERROR] {e}")

                            elif fc.name in ("send_prompt_to_antigravity", "modify_game_code"):
                                instruction = fc.args.get("instruction", "").strip()
                                await broadcast_project_log(slug, f"[ARCHITECT] Antigravity build started: \"{instruction[:80]}...\"", "info")
                                if not ws.closed:
                                    await ws.send_json({"type": "show_loader", "text": f"Antigravity is coding: {instruction[:60]}..."})
                                    await ws.send_json({"type": "set_command_input", "text": ""})

                                # Send immediate tool response so Gemini Live voice loop stays unblocked
                                tool_resp = types.LiveClientToolResponse(
                                    function_responses=[
                                        types.FunctionResponse(
                                            name=fc.name,
                                            id=fc.id,
                                            response={
                                                "result": f"Antigravity engine has received prompt: '{instruction}' and is now compiling the game files in the background. Tell the creator you started building it, and continue talking with them about gameplay mechanics, graphics, or further ideas while it builds."
                                            }
                                        )
                                    ]
                                )
                                try:
                                    await session.send(input=tool_resp)
                                except Exception as e:
                                    print(f"[LIVE TOOL SEND ERROR] {e}")

                                # Run code generation in background without freezing voice streaming
                                asyncio.create_task(_run_antigravity_builder(slug, session_user, api_key, instruction, ws, session))
            except asyncio.CancelledError:
                break
            except Exception as turn_err:
                print(f"[LIVE RECEIVE TURN ERROR] {turn_err}")
                if ws.closed or ws not in ACTIVE_LIVE_SESSIONS:
                    break
                err_str = str(turn_err).lower()
                if "connection closed" in err_str or "closed" in err_str or "1000" in err_str or "1006" in err_str:
                    break
                await asyncio.sleep(0.05)
    except asyncio.CancelledError:
        pass
    except Exception as e:
        print(f"[LIVE RECEIVE FATAL ERROR] {e}")

async def stop_gemini_live_session(ws: web.WebSocketResponse):
    """Gracefully terminates an active Gemini Live session."""
    if ws in ACTIVE_LIVE_SESSIONS:
        item = ACTIVE_LIVE_SESSIONS.pop(ws, None)
        if item:
            task = item.get("receive_task")
            session = item.get("session")
            slug = item.get("slug")
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            cm = item.get("cm")
            if cm:
                try:
                    await cm.__aexit__(None, None, None)
                except Exception:
                    pass
            elif session:
                try:
                    await session.close()
                except Exception:
                    pass
            if not ws.closed:
                try:
                    await ws.send_json({"type": "live_status", "status": "disconnected"})
                except Exception:
                    pass
            if slug:
                await broadcast_project_log(slug, "[LIVE] Disconnected from Gemini 3.8 Live", "live")

# --- WebSocket Hub: /ws/studio (Section 19, 20, 21, 22) ---

async def handle_ws_studio(request: web.Request) -> web.WebSocketResponse:
    slug = request.query.get("slug", "").lower()
    token = request.query.get("token", "")
    requested_role = request.query.get("role", "spectator")
    
    if not slug:
        return web.Response(text="Missing slug", status=400)
        
    # Authenticate role before accepting (Section 19)
    session_user = await get_session_user(request)
    role = "spectator"
    
    # Check if this connection belongs to the creator
    if session_user:
        user_proj = await database.get_project(session_user["id"], slug)
        if user_proj:
            role = "creator"
        else:
            user_proj = await database.get_project_by_username_and_slug(session_user.get("username", ""), slug)
            if user_proj:
                role = "creator"
            elif projects_manager.get_user_project_dir(session_user["id"], slug).exists():
                role = "creator"
            
    # If not creator, strictly authenticate spectator access
    if role != "creator":
        spectator_proj = None
        if token:
            spectator_proj = await database.get_project_by_spectator_token(token)
            
        if not spectator_proj and database.projects_col is not None:
            # Check if project exists by slug and is public
            spectator_proj = await database.projects_col.find_one({
                "slug": slug,
                "is_public": {"$ne": False}
            })
            
        if not spectator_proj:
            # Reject invalid sessions (Section 19)
            return web.Response(text="Unauthorized: Project or spectator session not found.", status=401)

    ws = web.WebSocketResponse()
    await ws.prepare(request)
    
    if slug not in ACTIVE_STUDIO_WS:
        ACTIVE_STUDIO_WS[slug] = {
            "creator": set(),
            "spectators": set(),
            "last_seen": {}
        }
        
    slot = ACTIVE_STUDIO_WS[slug]
    if role == "creator":
        slot["creator"].add(ws)
    else:
        slot["spectators"].add(ws)
        
    slot["last_seen"][ws] = time.time()
    
    # Broadcast connection status
    await broadcast_status(slug)
    
    try:
        async for msg in ws:
            now = time.time()
            slot["last_seen"][ws] = now
            
            if msg.type == web.WSMsgType.TEXT:
                try:
                    data = json.loads(msg.data)
                    msg_type = data.get("type")
                    
                    if msg_type == "heartbeat":
                        # Client ping to keep alive
                        continue

                    elif msg_type == "connect_live":
                        if not session_user:
                            if not ws.closed:
                                await ws.send_json({
                                    "type": "live_error",
                                    "message": "Authentication required. Please sign in to connect Gemini Live."
                                })
                        elif role != "creator":
                            if not ws.closed:
                                await ws.send_json({
                                    "type": "live_error",
                                    "message": "Only the creator of this game can connect to Gemini Live."
                                })
                        else:
                            await start_gemini_live_session(ws, slug, session_user)

                    elif msg_type == "disconnect_live":
                        if role == "creator":
                            await stop_gemini_live_session(ws)

                    elif msg_type == "audio_chunk":
                        # Forward audio chunk from creator's microphone to Gemini Live session
                        if role == "creator" and ws in ACTIVE_LIVE_SESSIONS:
                            pcm_b64 = data.get("pcm")
                            if pcm_b64:
                                try:
                                    pcm_bytes = base64.b64decode(pcm_b64)
                                    live_sess = ACTIVE_LIVE_SESSIONS[ws]["session"]
                                    await live_sess.send(input=types.LiveClientRealtimeInput(
                                        media_chunks=[types.Blob(data=pcm_bytes, mime_type="audio/pcm;rate=16000")]
                                    ))
                                except Exception as audio_err:
                                    print(f"[AUDIO CHUNK SEND ERROR] {audio_err}")

                    elif msg_type == "audio_end":
                        # Creator finished speaking turn (signals turn complete to Gemini Live)
                        if role == "creator" and ws in ACTIVE_LIVE_SESSIONS:
                            live_sess = ACTIVE_LIVE_SESSIONS[ws]["session"]
                            transcript = data.get("transcript", "").strip()
                            try:
                                if transcript:
                                    # Send recognized speech transcript to guarantee 100% accurate comprehension
                                    await live_sess.send(input=transcript, end_of_turn=True)
                                else:
                                    await live_sess.send(input=types.LiveClientContent(turn_complete=True))
                            except Exception as e:
                                print(f"[LIVE] Error sending turn_complete: {e}")

                    elif msg_type == "live_text":
                        # Creator sends text directly to Gemini 3.8 Live session
                        if role == "creator" and ws in ACTIVE_LIVE_SESSIONS:
                            text_input = data.get("text", "").strip()
                            if text_input:
                                live_sess = ACTIVE_LIVE_SESSIONS[ws]["session"]
                                await live_sess.send(input=text_input, end_of_turn=True)
                        
                    elif msg_type == "command":
                        # ONLY creator is authorized to execute commands (Section 21)
                        if role != "creator":
                            await ws.send_json({
                                "type": "log",
                                "level": "error",
                                "message": "Spectators are not authorized to send creator commands."
                            })
                            continue
                            
                        prompt = data.get("prompt", "").strip()
                        if prompt and session_user:
                            profile = await database.get_user_profile(session_user["id"])
                            api_key = profile.get("studio_api_key") if profile else None
                            if api_key:
                                if not ws.closed:
                                    await ws.send_json({"type": "set_command_input", "text": ""})
                                live_sess = ACTIVE_LIVE_SESSIONS.get(ws, {}).get("session")
                                if live_sess:
                                    try:
                                        await live_sess.send(
                                            input=f"[System: The creator submitted the prompt to Antigravity: '{prompt}'. Tell the creator you see they launched the build and Antigravity is coding now! Keep chatting with them while it compiles.]",
                                            end_of_turn=True
                                        )
                                    except Exception:
                                        pass
                                asyncio.create_task(_run_antigravity_builder(slug, session_user, api_key, prompt, ws, live_sess))
                                    
                    elif msg_type == "video_frame":
                        # Only creator can stream screen frames (Section 21, 81)
                        if role == "creator":
                            frame_data = data.get("data")
                            if frame_data:
                                await broadcast_screen_frame(slug, frame_data)
                                # Forward frame to Gemini Live vision
                                if ws in ACTIVE_LIVE_SESSIONS:
                                    try:
                                        jpeg_bytes = base64.b64decode(frame_data)
                                        live_sess = ACTIVE_LIVE_SESSIONS[ws]["session"]
                                        await live_sess.send(input=types.LiveClientRealtimeInput(
                                            media_chunks=[types.Blob(data=jpeg_bytes, mime_type="image/jpeg")]
                                        ))
                                    except Exception:
                                        pass
                                
                except Exception as e:
                    print(f"[WS] Error handling message: {e}")
                    
            elif msg.type == web.WSMsgType.BINARY:
                # Binary audio data from PTT or streaming mic
                if role == "creator" and ws in ACTIVE_LIVE_SESSIONS and len(msg.data) > 0:
                    try:
                        live_sess = ACTIVE_LIVE_SESSIONS[ws]["session"]
                        await live_sess.send(input=types.LiveClientRealtimeInput(
                            media_chunks=[types.Blob(data=msg.data, mime_type="audio/pcm;rate=16000")]
                        ))
                    except Exception:
                        pass
                
    finally:
        # Cleanly stop and release Gemini Live session on socket close or disconnect
        await stop_gemini_live_session(ws)
        if slug in ACTIVE_STUDIO_WS:
            slot = ACTIVE_STUDIO_WS[slug]
            slot["creator"].discard(ws)
            slot["spectators"].discard(ws)
            slot["last_seen"].pop(ws, None)
            if not slot["creator"] and not slot["spectators"]:
                del ACTIVE_STUDIO_WS[slug]
            else:
                await broadcast_status(slug)
                
    return ws

async def broadcast_status(slug: str):
    if slug not in ACTIVE_STUDIO_WS:
        return
    slot = ACTIVE_STUDIO_WS[slug]
    total_users = len(slot["creator"]) + len(slot["spectators"])
    creator_online = len(slot["creator"]) > 0
    msg = {
        "type": "status",
        "connected_users": total_users,
        "creator_online": creator_online
    }
    all_clients = slot["creator"] | slot["spectators"]
    for c in list(all_clients):
        if not c.closed:
            try:
                await c.send_json(msg)
            except Exception:
                pass

async def broadcast_project_update(slug: str, message: dict):
    if slug in ACTIVE_STUDIO_WS:
        slot = ACTIVE_STUDIO_WS[slug]
        all_clients = slot["creator"] | slot["spectators"]
        for client in list(all_clients):
            if not client.closed:
                try:
                    await client.send_json(message)
                except Exception:
                    pass

async def broadcast_project_log(slug: str, message_text: str, level: str = "info"):
    if slug in ACTIVE_STUDIO_WS:
        slot = ACTIVE_STUDIO_WS[slug]
        msg = {
            "type": "log",
            "message": message_text,
            "level": level,
            "timestamp": int(time.time())
        }
        all_clients = slot["creator"] | slot["spectators"]
        for client in list(all_clients):
            if not client.closed:
                try:
                    await client.send_json(msg)
                except Exception:
                    pass

async def broadcast_screen_frame(slug: str, frame_data: str):
    if slug in ACTIVE_STUDIO_WS:
        slot = ACTIVE_STUDIO_WS[slug]
        msg = {
            "type": "screen_frame",
            "data": frame_data
        }
        # Send screen frames only to spectators
        for spectator in list(slot["spectators"]):
            if not spectator.closed:
                try:
                    await spectator.send_json(msg)
                except Exception:
                    pass

# --- Background Idle Monitor (Section 22) ---

async def idle_monitor_loop():
    """
    Checks WebSocket connections for idle timeouts:
    - 120s no heartbeat -> idle warning
    - 150s no heartbeat -> idle disconnect
    """
    while True:
        try:
            await asyncio.sleep(10)
            now = time.time()
            for slug, slot in list(ACTIVE_STUDIO_WS.items()):
                for ws, last_time in list(slot["last_seen"].items()):
                    elapsed = now - last_time
                    if elapsed > 150:
                        if not ws.closed:
                            try:
                                await ws.send_json({
                                    "type": "idle_disconnect",
                                    "message": "Session disconnected due to 150s of inactivity."
                                })
                                await ws.close()
                            except Exception:
                                pass
                    elif elapsed > 120:
                        if not ws.closed:
                            try:
                                await ws.send_json({
                                    "type": "idle_warning",
                                    "message": "Studio inactive. You will be disconnected soon."
                                })
                            except Exception:
                                pass
        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"[IDLE MONITOR] Error: {e}")

# --- App Initialization ---

async def init_app():
    app = web.Application(middlewares=[security_headers_middleware])
    
    # Startup tasks
    app.on_startup.append(lambda a: database.init_db())
    
    async def start_background_tasks(app):
        app['idle_task'] = asyncio.create_task(idle_monitor_loop())
    async def cleanup_background_tasks(app):
        if 'idle_task' in app:
            app['idle_task'].cancel()
            await asyncio.gather(app['idle_task'], return_exceptions=True)
            
    app.on_startup.append(start_background_tasks)
    app.on_cleanup.append(cleanup_background_tasks)
    
    # Static files route
    app.router.add_static("/static", config.STATIC_DIR)
    
    # Page Routes
    app.router.add_get("/", handle_index)
    app.router.add_get("/studio", handle_studio)
    app.router.add_get("/spectate/{token}", handle_spectate)
    app.router.add_get("/spectate/{username}/{slug}", handle_spectate)
    
    # Auth
    app.router.add_get("/auth/login", handle_login)
    app.router.add_get("/auth/callback", handle_auth_callback)
    app.router.add_get("/auth/logout", handle_logout)
    
    # API
    app.router.add_post("/api/save-key", api_save_key)
    app.router.add_post("/api/create-project", api_create_project)
    app.router.add_post("/api/modify-project", api_modify_project)
    app.router.add_post("/api/delete-project", api_delete_project)
    app.router.add_post("/api/leave-vc", api_leave_vc)
    app.router.add_get("/api/project-files/{slug}", api_project_files)
    app.router.add_get("/api/project-logs/{slug}", api_project_logs)
    app.router.add_post("/api/project-logs/{slug}", api_save_project_log)
    app.router.add_get("/api/community-projects", api_community_projects)
    app.router.add_get("/api/download-zip/{username}/{slug}", api_download_zip)
    
    # WebSocket
    app.router.add_get("/ws/studio", handle_ws_studio)
    
    # Creator Studio Project Route
    app.router.add_get("/{username}/{slug}/studio", handle_user_slug_studio)

    # Dynamic Game Hosting (Sandboxed Game Iframes)
    app.router.add_get("/{username}/{slug}", handle_game_redirect)
    app.router.add_get("/{username}/{slug}/", handle_game_asset)
    app.router.add_get("/{username}/{slug}/{file:.*}", handle_game_asset)
    
    # User Profile / Portfolio Page
    app.router.add_get("/{username}", handle_user_profile)
    
    return app

if __name__ == "__main__":
    print(f"[YULYA STUDIO] Server starting on port {config.PORT}...")
    web.run_app(init_app(), port=config.PORT)
