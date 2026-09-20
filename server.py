import os
import io
import json
import time
import asyncio
import secrets
from pathlib import Path
from aiohttp import web, ClientSession
import jinja2

import config
import database
import projects_manager
import ai_engine

# In-memory sessions: { session_token: { "user": user_dict, "created_at": float } }
SESSION_STORE = {}

# Active WebSocket connections: { slug: set(ws) }
ACTIVE_STUDIO_WS = {}

async def get_session_user(request):
    token = request.cookies.get("yulya_studio_session")
    if not token:
        return None
    if token in SESSION_STORE:
        return SESSION_STORE[token].get("user")
    # Query database if present
    if database.db is not None:
        doc = await database.db['studio_sessions'].find_one({"token": token})
        if doc:
            SESSION_STORE[token] = doc
            return doc.get("user")
    return None

async def set_session_user(response: web.Response, user_data: dict):
    token = secrets.token_urlsafe(32)
    session_payload = {
        "token": token,
        "user": user_data,
        "created_at": time.time()
    }
    SESSION_STORE[token] = session_payload
    if database.db is not None:
        await database.db['studio_sessions'].update_one(
            {"token": token},
            {"$set": session_payload},
            upsert=True
        )
    response.set_cookie(
        "yulya_studio_session",
        token,
        max_age=86400 * 30, # 30 days
        httponly=True,
        samesite="Lax"
    )
    return token

async def render_template(template_name: str, context: dict = None):
    context = context or {}
    template_path = config.TEMPLATES_DIR / template_name
    template_content = template_path.read_text(encoding="utf-8")
    env = jinja2.Environment(autoescape=True)
    template = env.from_string(template_content)
    rendered = template.render(**context)
    return web.Response(text=rendered, content_type="text/html")

# --- Page Routes ---

async def handle_index(request):
    """Public Arcade Gallery Homepage"""
    user = await get_session_user(request)
    return await render_template("index.html", {"user": user})

async def handle_studio(request):
    """Creator Studio Workspace or Onboarding Setup"""
    user = await get_session_user(request)
    
    if not user:
        return await render_template("onboarding.html", {"user": None})
        
    profile = await database.get_user_profile(user["id"])
    has_api_key = profile and profile.get("studio_api_key")
    
    if not has_api_key:
        return await render_template("onboarding.html", {"user": user})
        
    # User is ready: load their projects
    projects = await database.list_user_projects(user["id"])
    active_slug = request.query.get("slug")
    
    # If user has no projects, create a default starter game
    if not projects:
        default_slug = "neon-dodge"
        projects_manager.create_starter_game(user["id"], user["username"], default_slug, "Neon Dodge")
        await database.save_project(
            user_id=user["id"],
            username=user["username"],
            slug=default_slug,
            title="Neon Dodge",
            description="Starter retro arcade game built with Yulya Studio."
        )
        projects = await database.list_user_projects(user["id"])
        active_slug = default_slug
    elif not active_slug:
        active_slug = projects[0]["slug"]
        
    return await render_template("studio.html", {
        "user": user,
        "projects": projects,
        "active_slug": active_slug
    })

async def handle_spectate(request):
    """Spectator HUD for friends in VC"""
    username = request.match_info["username"]
    slug = request.match_info["slug"]
    
    proj = await database.get_project_by_username_and_slug(username, slug)
    title = proj.get("title", slug) if proj else slug
    
    return await render_template("spectator.html", {
        "author": username,
        "slug": slug,
        "title": title
    })

# --- Discord OAuth Routes ---

async def handle_login(request):
    return web.HTTPFound(config.DISCORD_OAUTH_URL)

async def handle_auth_callback(request):
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
    
    async with ClientSession() as client:
        # 1. Exchange code for access token
        async with client.post("https://discord.com/api/oauth2/token", data=data) as token_resp:
            token_data = await token_resp.json()
            access_token = token_data.get("access_token")
            
        if not access_token:
            return web.HTTPFound("/studio")
            
        # 2. Fetch Discord user profile
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

async def handle_logout(request):
    token = request.cookies.get("yulya_studio_session")
    if token and token in SESSION_STORE:
        del SESSION_STORE[token]
    response = web.HTTPFound("/")
    response.del_cookie("yulya_studio_session")
    return response

# --- API Endpoints ---

async def api_save_key(request):
    user = await get_session_user(request)
    if not user:
        return web.json_response({"success": False, "error": "Not authenticated with Discord."}, status=401)
        
    try:
        body = await request.json()
        key = body.get("api_key", "").strip()
        res = await database.save_user_api_key(user["id"], key, user["username"])
        return web.json_response(res)
    except Exception as e:
        return web.json_response({"success": False, "error": str(e)}, status=400)

async def api_create_project(request):
    user = await get_session_user(request)
    if not user:
        return web.json_response({"success": False, "error": "Not authenticated."}, status=401)
        
    body = await request.json()
    title = body.get("title", "New Game").strip()
    slug = title.lower().replace(" ", "-")
    slug = "".join(c for c in slug if c.isalnum() or c in "-_")
    
    existing = await database.get_project(user["id"], slug)
    if existing:
        slug = f"{slug}-{secrets.token_hex(2)}"
        
    projects_manager.create_starter_game(user["id"], user["username"], slug, title)
    await database.save_project(
        user_id=user["id"],
        username=user["username"],
        slug=slug,
        title=title,
        description=f"A new web game by {user['username']}."
    )
    return web.json_response({"success": True, "slug": slug})

async def api_modify_project(request):
    user = await get_session_user(request)
    if not user:
        return web.json_response({"success": False, "error": "Not authenticated."}, status=401)
        
    body = await request.json()
    slug = body.get("slug")
    prompt = body.get("prompt")
    
    profile = await database.get_user_profile(user["id"])
    api_key = profile.get("studio_api_key")
    if not api_key:
        return web.json_response({"success": False, "error": "No Gemini API key saved."}, status=400)
        
    result = await ai_engine.process_code_request(api_key, user["id"], user["username"], slug, prompt)
    
    # Broadcast hot-reload to all connected WebSockets (creator + spectators)
    if result.get("success"):
        await broadcast_project_update(slug, {
            "type": "code_update",
            "summary": result["summary"],
            "content": result["content"]
        })
        
    return web.json_response(result)

async def api_community_projects(request):
    projects = await database.list_community_arcade(limit=50)
    return web.json_response(projects)

async def api_download_zip(request):
    username = request.match_info["username"]
    slug = request.match_info["slug"]
    
    proj = await database.get_project_by_username_and_slug(username, slug)
    if not proj:
        return web.Response(text="Project not found", status=404)
        
    zip_buf = projects_manager.create_zip_archive(proj["user_id"], slug)
    return web.Response(
        body=zip_buf.read(),
        content_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename={slug}.zip"}
    )

# --- Static Game Hosting: /{username}/{slug}/* ---

async def handle_game_asset(request):
    username = request.match_info["username"].lower()
    slug = request.match_info["slug"].lower()
    filename = request.match_info.get("file", "index.html")
    if not filename:
        filename = "index.html"
        
    proj = await database.get_project_by_username_and_slug(username, slug)
    if not proj:
        return web.Response(text="Game not found", status=404)
        
    safe_name = os.path.basename(filename)
    pdir = projects_manager.get_user_project_dir(proj["user_id"], slug)
    target = pdir / safe_name
    
    if not target.exists():
        return web.Response(text="File not found", status=404)
        
    content_type = "text/html"
    if safe_name.endswith(".css"): content_type = "text/css"
    elif safe_name.endswith(".js"): content_type = "application/javascript"
    elif safe_name.endswith(".json"): content_type = "application/json"
    elif safe_name.endswith(".png"): content_type = "image/png"
    elif safe_name.endswith(".jpg") or safe_name.endswith(".jpeg"): content_type = "image/jpeg"
    elif safe_name.endswith(".svg"): content_type = "image/svg+xml"
    
    return web.Response(
        body=target.read_bytes(),
        content_type=content_type,
        headers={"Cache-Control": "no-store, no-cache, must-revalidate"}
    )

# --- WebSocket Hub: /ws/studio ---

async def handle_ws_studio(request):
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    
    slug = request.query.get("slug", "default")
    if slug not in ACTIVE_STUDIO_WS:
        ACTIVE_STUDIO_WS[slug] = set()
    ACTIVE_STUDIO_WS[slug].add(ws)
    
    try:
        async for msg in ws:
            if msg.type == web.WSMsgType.TEXT:
                try:
                    data = json.loads(msg.data)
                    if data.get("type") == "video_frame":
                        pass
                except Exception:
                    pass
            elif msg.type == web.WSMsgType.BINARY:
                pass
    finally:
        if slug in ACTIVE_STUDIO_WS:
            ACTIVE_STUDIO_WS[slug].discard(ws)
            if not ACTIVE_STUDIO_WS[slug]:
                del ACTIVE_STUDIO_WS[slug]
    return ws

async def broadcast_project_update(slug: str, message: dict):
    if slug in ACTIVE_STUDIO_WS:
        dead = set()
        for client in ACTIVE_STUDIO_WS[slug]:
            if client.closed:
                dead.add(client)
            else:
                try:
                    await client.send_json(message)
                except Exception:
                    dead.add(client)
        ACTIVE_STUDIO_WS[slug] -= dead

# --- App Initialization ---

async def init_app():
    app = web.Application()
    
    # Database setup on startup
    app.on_startup.append(lambda a: database.init_db())
    
    # Routes
    app.router.add_get("/", handle_index)
    app.router.add_get("/studio", handle_studio)
    app.router.add_get("/spectate/{username}/{slug}", handle_spectate)
    
    # Auth
    app.router.add_get("/auth/login", handle_login)
    app.router.add_get("/auth/callback", handle_auth_callback)
    app.router.add_get("/auth/logout", handle_logout)
    
    # API
    app.router.add_post("/api/save-key", api_save_key)
    app.router.add_post("/api/create-project", api_create_project)
    app.router.add_post("/api/modify-project", api_modify_project)
    app.router.add_get("/api/community-projects", api_community_projects)
    app.router.add_get("/api/download-zip/{username}/{slug}", api_download_zip)
    
    # WebSocket
    app.router.add_get("/ws/studio", handle_ws_studio)
    
    # Dynamic Game Hosting
    app.router.add_get("/{username}/{slug}/", handle_game_asset)
    app.router.add_get("/{username}/{slug}/{file:.*}", handle_game_asset)
    
    return app

if __name__ == "__main__":
    app = asyncio.run(init_app())
    print(f"[YULYA STUDIO] Server running on port {config.PORT}...")
    web.run_app(app, port=config.PORT)
