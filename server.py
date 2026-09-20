import os
import io
import json
import time
import asyncio
import secrets
from pathlib import Path
from datetime import datetime, timezone
from aiohttp import web, ClientSession
import jinja2

import config
import database
import projects_manager
import ai_engine

# In-memory sessions cache: { session_token: { "user": user_dict, "created_at": float } }
SESSION_STORE = {}

# Active WebSocket connections:
# { slug: { "creator": set([ws]), "spectators": set([ws]), "last_seen": { ws: float } } }
ACTIVE_STUDIO_WS = {}

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
    """Public Arcade Gallery Homepage (Section 35)"""
    user = await get_session_user(request)
    return await render_template("index.html", {"user": user})

async def handle_studio(request: web.Request) -> web.Response:
    """Creator Studio Workspace or Onboarding Setup (Section 36, 37)"""
    user = await get_session_user(request)
    
    if not user:
        return await render_template("onboarding.html", {"user": None})
        
    profile = await database.get_user_profile(user["id"])
    has_api_key = profile and profile.get("studio_api_key")
    
    if not has_api_key:
        return await render_template("onboarding.html", {"user": user})
        
    projects = await database.list_user_projects(user["id"])
    active_slug = request.query.get("slug")
    
    # Auto-create default starter game "Neon Dodge" if user has no projects (Section 73)
    if not projects:
        default_slug = "neon-dodge"
        projects_manager.create_starter_game(user["id"], user["username"], default_slug, "Neon Dodge")
        await database.save_project(
            user_id=user["id"],
            username=user["username"],
            slug=default_slug,
            title="Neon Dodge",
            description="Starter retro neon dodge game created with Yulya Studio."
        )
        projects = await database.list_user_projects(user["id"])
        active_slug = default_slug
    elif not active_slug or not any(p["slug"] == active_slug for p in projects):
        active_slug = projects[0]["slug"]
        
    active_project = next((p for p in projects if p["slug"] == active_slug), projects[0])
    
    return await render_template("studio.html", {
        "user": user,
        "projects": projects,
        "active_slug": active_slug,
        "active_project": active_project,
        "spectator_token": active_project.get("spectator_token", "")
    })

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
                
        response = web.HTTPFound("/studio")
        if "id" in user_data:
            user_info = {
                "id": int(user_data["id"]),
                "username": user_data["username"],
                "avatar": user_data.get("avatar")
            }
            await set_session_user(response, user_info)
        return response
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
            
        # Broadcast "thinking" log to connected WebSockets
        await broadcast_project_log(slug, "Thinking... Google AI Studio is analyzing your project.", "thinking")
        
        result = await ai_engine.process_code_request(api_key, user["id"], user["username"], slug, prompt)
        
        if result.get("success"):
            # Hot-reload update to creator + spectators (Section 20)
            await broadcast_project_update(slug, {
                "type": "code_update",
                "summary": result["summary"],
                "content": result["content"],
                "timestamp": int(time.time())
            })
            await broadcast_project_log(slug, f"Updated files: {result['summary']}", "success")
        else:
            await broadcast_project_log(slug, f"Failed: {result.get('error')}", "error")
            
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
    if not safe_name or ".." in safe_name:
        safe_name = "index.html"
        
    pdir = projects_manager.get_user_project_dir(proj["user_id"], slug)
    target = (pdir / safe_name).resolve()
    
    if not str(target).startswith(str(pdir)) or not target.exists() or not target.is_file():
        return web.Response(text="File not found", status=404)
        
    content_type = "text/html; charset=utf-8"
    if safe_name.endswith(".css"): content_type = "text/css; charset=utf-8"
    elif safe_name.endswith(".js"): content_type = "application/javascript; charset=utf-8"
    elif safe_name.endswith(".json"): content_type = "application/json; charset=utf-8"
    elif safe_name.endswith(".png"): content_type = "image/png"
    elif safe_name.endswith((".jpg", ".jpeg")): content_type = "image/jpeg"
    elif safe_name.endswith(".svg"): content_type = "image/svg+xml"
    
    return web.Response(
        body=target.read_bytes(),
        content_type=content_type,
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate",
            "X-Content-Type-Options": "nosniff"
        }
    )

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
                                await broadcast_project_log(slug, f"Processing request: '{prompt}'", "thinking")
                                res = await ai_engine.process_code_request(
                                    api_key, session_user["id"], session_user["username"], slug, prompt
                                )
                                if res.get("success"):
                                    await broadcast_project_update(slug, {
                                        "type": "code_update",
                                        "summary": res["summary"],
                                        "content": res["content"],
                                        "timestamp": int(time.time())
                                    })
                                    await broadcast_project_log(slug, f"AI: {res['summary']}", "success")
                                else:
                                    await broadcast_project_log(slug, f"AI Error: {res.get('error')}", "error")
                                    
                    elif msg_type == "video_frame":
                        # Only creator can stream screen frames (Section 21, 81)
                        if role == "creator":
                            frame_data = data.get("data")
                            if frame_data:
                                await broadcast_screen_frame(slug, frame_data)
                                
                except Exception as e:
                    print(f"[WS] Error handling message: {e}")
                    
            elif msg.type == web.WSMsgType.BINARY:
                # Binary audio data from PTT
                pass
                
    finally:
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
    app.router.add_get("/api/community-projects", api_community_projects)
    app.router.add_get("/api/download-zip/{username}/{slug}", api_download_zip)
    
    # WebSocket
    app.router.add_get("/ws/studio", handle_ws_studio)
    
    # Dynamic Game Hosting (Sandboxed Game Iframes)
    app.router.add_get("/{username}/{slug}", handle_game_redirect)
    app.router.add_get("/{username}/{slug}/", handle_game_asset)
    app.router.add_get("/{username}/{slug}/{file:.*}", handle_game_asset)
    
    return app

if __name__ == "__main__":
    print(f"[YULYA STUDIO] Server starting on port {config.PORT}...")
    web.run_app(init_app(), port=config.PORT)
