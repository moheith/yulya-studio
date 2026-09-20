import os
import re
import asyncio
import secrets
from datetime import datetime, timezone
from motor.motor_asyncio import AsyncIOMotorClient
from google import genai
from google.genai.errors import APIError
import config

db_client = None
db = None
users_col = None
profiles_col = None
projects_col = None
sessions_col = None
signals_col = None

async def init_db():
    global db_client, db, users_col, profiles_col, projects_col, sessions_col, signals_col
    if not config.MONGO_URI:
        print("[DATABASE] Warning: MONGO_URI not configured!")
        return False
    
    try:
        db_client = AsyncIOMotorClient(config.MONGO_URI, maxIdleTimeMS=60000)
        db = db_client['yulya_bot_db']
        users_col = db['user_profiles']
        profiles_col = db['studio_profiles']
        projects_col = db['studio_projects']
        sessions_col = db['studio_sessions']
        signals_col = db['studio_signals']
        
        # 1. Studio Profiles indexes
        await profiles_col.create_index([("user_id", 1)], unique=True)
        await profiles_col.create_index([("username", 1)])
        await profiles_col.create_index([("login_id", 1)])
        
        # 2. Projects indexes
        await projects_col.create_index([("user_id", 1), ("slug", 1)], unique=True)
        await projects_col.create_index([("updated_at", -1)])
        await projects_col.create_index([("spectator_token", 1)], sparse=True)
        
        # 3. Sessions indexes (TTL: 30 days)
        await sessions_col.create_index([("token", 1)], unique=True)
        try:
            await sessions_col.create_index([("created_at_dt", 1)], expireAfterSeconds=86400 * 30)
        except Exception:
            pass

        # 4. Signals index (TTL: 10 minutes)
        try:
            await signals_col.create_index([("created_at_dt", 1)], expireAfterSeconds=600)
        except Exception:
            pass

        print("[DATABASE] Connected to MongoDB (yulya_bot_db) successfully.")
        return True
    except Exception as e:
        print(f"[DATABASE] Connection error: {e}")
        return False

async def verify_google_ai_studio_key(api_key: str) -> tuple[bool, str]:
    """
    Verifies that the provided Google AI Studio API key is valid by sending a minimal ping request.
    Uses gemma-4-31b-it as primary check with gemini-2.5-flash fallback.
    Returns (is_valid, message).
    """
    if not api_key or not isinstance(api_key, str) or len(api_key.strip()) < 15:
        return False, "Google AI Studio API key is too short or invalid format."
    
    cleaned_key = api_key.strip()
    
    def _test_call():
        client = genai.Client(api_key=cleaned_key)
        for model_name in [
            "gemini-3.8-flash",
            "gemini-3.7-flash",
            "gemini-3.6-flash",
            "gemini-3.5-flash",
            "gemini-3.5-flash-lite",
            "gemini-3.1-flash-lite",
            "gemma-4-31b-it",
            "gemini-2.5-flash"
        ]:
            try:
                resp = client.models.generate_content(
                    model=model_name,
                    contents="ping"
                )
                if resp and hasattr(resp, 'text'):
                    return True, "Google AI Studio API key verified successfully."
            except APIError as ae:
                msg = str(ae)
                if "API_KEY_INVALID" in msg or "not valid" in msg.lower() or ae.code in [400, 403]:
                    return False, "This Google AI Studio API key could not be verified by Google AI Studio. Please check the key and try again."
                elif "RESOURCE_EXHAUSTED" in msg or ae.code == 429:
                    return True, "Key is valid, though current quota limit is reached."
                # On 5xx server errors or unsupported model, try fallback
                continue
            except Exception as e:
                err_str = str(e)
                if "API_KEY_INVALID" in err_str or "not valid" in err_str.lower():
                    return False, "This Google AI Studio API key could not be verified. Check the key and try again."
                continue
        return False, "Unable to verify API key with Google AI Studio. Please verify the key and try again."

    try:
        is_valid, msg = await asyncio.to_thread(_test_call)
        return is_valid, msg
    except Exception as e:
        return False, f"Verification failed: {str(e)[:100]}"

# Backward-compatibility alias
verify_gemini_api_key = verify_google_ai_studio_key

async def get_user_profile(user_id: int):
    """Retrieves a user profile by Discord User ID (handles int and string representations)."""
    if users_col is None:
        return None
    try:
        uid_int = int(user_id)
    except (ValueError, TypeError):
        uid_int = None
    uid_str = str(user_id)
    query_or = []
    if uid_int is not None:
        query_or.append({"user_id": uid_int})
    query_or.append({"user_id": uid_str})
    
    # Prioritize document with studio_api_key
    doc = await users_col.find_one({"$or": query_or, "studio_api_key": {"$exists": True, "$ne": ""}})
    if not doc:
        doc = await users_col.find_one({"$or": query_or})
    return doc

# --- Studio Profiles Management (Dedicated user profile & game tracking) ---

async def save_or_update_profile(user_id: int, username: str, display_name: str = None, avatar: str = None) -> dict:
    """
    Maintains a distinct user profile in studio_profiles storing:
    - user_id (numeric Discord ID)
    - login_id (Discord login handle / identifier)
    - username (Discord username / handle)
    - profile_name (Profile name)
    - display_name (Display name)
    - avatar URL or hash
    - game_names: array of all names of the games created by the user
    - created_games: array of created game objects/slugs with titles, created dates, and stats
    - created_at, updated_at
    """
    if profiles_col is None:
        return None
        
    user_id_int = int(user_id)
    clean_username = username.strip().lower()
    clean_display = display_name or username
    now = datetime.now(timezone.utc)
    
    existing = await profiles_col.find_one({"user_id": user_id_int})
    if existing:
        existing_games = existing.get("created_games", [])
        existing_game_names = existing.get("game_names") or [g.get("title", g.get("slug")) for g in existing_games]
        
        update_fields = {
            "login_id": clean_username,
            "username": clean_username,
            "profile_name": clean_display,
            "display_name": clean_display,
            "game_names": existing_game_names,
            "updated_at": now
        }
        if avatar is not None:
            update_fields["avatar"] = avatar
            
        await profiles_col.update_one(
            {"user_id": user_id_int},
            {"$set": update_fields}
        )
        existing.update(update_fields)
        existing["_id"] = str(existing.get("_id", ""))
        return existing
    else:
        new_profile = {
            "user_id": user_id_int,
            "login_id": clean_username,
            "username": clean_username,
            "profile_name": clean_display,
            "display_name": clean_display,
            "avatar": avatar,
            "game_names": [],
            "created_games": [],
            "created_at": now,
            "updated_at": now
        }
        res = await profiles_col.insert_one(new_profile)
        new_profile["_id"] = str(res.inserted_id)
        return new_profile

async def get_profile_by_user_id(user_id: int) -> dict | None:
    """Retrieves a studio profile record by user_id."""
    if profiles_col is None:
        return None
    doc = await profiles_col.find_one({"user_id": int(user_id)})
    if doc:
        doc["_id"] = str(doc.get("_id", ""))
    return doc

# Alias for backward compatibility / clarity
get_studio_profile = get_profile_by_user_id

async def get_profile_by_username(username: str) -> dict | None:
    """Retrieves a studio profile record by username or login_id (case-insensitive)."""
    if profiles_col is None:
        return None
    clean = username.strip().lower()
    doc = await profiles_col.find_one({"$or": [{"username": clean}, {"login_id": clean}]})
    if not doc and projects_col is not None:
        # Check if existing projects can seed/backfill the studio profile
        cursor = projects_col.find({"username": clean}).sort("updated_at", -1)
        projs = await cursor.to_list(length=100)
        if projs:
            first_proj = projs[0]
            user_id = first_proj["user_id"]
            created_games = []
            game_names = []
            for p in projs:
                g_title = p.get("title") or p.get("slug")
                game_names.append(g_title)
                created_games.append({
                    "slug": p.get("slug"),
                    "title": g_title,
                    "description": p.get("description", ""),
                    "tags": p.get("tags", []),
                    "created_at": p.get("created_at", datetime.now(timezone.utc)).isoformat() if isinstance(p.get("created_at"), datetime) else str(p.get("created_at", "")),
                    "updated_at": p.get("updated_at", datetime.now(timezone.utc)).isoformat() if isinstance(p.get("updated_at"), datetime) else str(p.get("updated_at", "")),
                    "views": 0,
                    "plays": 0
                })
            now = datetime.now(timezone.utc)
            doc = {
                "user_id": int(user_id),
                "login_id": clean,
                "username": clean,
                "profile_name": clean,
                "display_name": clean,
                "avatar": None,
                "game_names": game_names,
                "created_games": created_games,
                "created_at": now,
                "updated_at": now
            }
            res = await profiles_col.insert_one(doc)
            doc["_id"] = str(res.inserted_id)
            return doc
    if doc:
        doc["_id"] = str(doc.get("_id", ""))
    return doc

async def sync_project_to_profile(user_id: int, username: str, project_doc: dict) -> bool:
    """Syncs created game information and game_names into the user's studio_profiles record."""
    if profiles_col is None:
        return False
    user_id_int = int(user_id)
    clean_username = username.strip().lower()
    safe_slug = project_doc["slug"]
    game_title = project_doc.get("title", safe_slug)
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    
    profile = await profiles_col.find_one({"user_id": user_id_int})
    if not profile:
        game_entry = {
            "slug": safe_slug,
            "title": game_title,
            "description": project_doc.get("description", ""),
            "tags": project_doc.get("tags", ["game", "canvas"]),
            "created_at": now_iso,
            "updated_at": now_iso,
            "views": 0,
            "plays": 0
        }
        await profiles_col.insert_one({
            "user_id": user_id_int,
            "login_id": clean_username,
            "username": clean_username,
            "profile_name": clean_username,
            "display_name": clean_username,
            "avatar": None,
            "game_names": [game_title],
            "created_games": [game_entry],
            "created_at": now,
            "updated_at": now
        })
        return True
        
    created_games = profile.get("created_games", [])
    found = False
    for g in created_games:
        if g.get("slug") == safe_slug:
            g["title"] = game_title
            g["description"] = project_doc.get("description", g.get("description", ""))
            g["tags"] = project_doc.get("tags", g.get("tags", ["game", "canvas"]))
            g["updated_at"] = now_iso
            found = True
            break
            
    if not found:
        created_games.append({
            "slug": safe_slug,
            "title": game_title,
            "description": project_doc.get("description", ""),
            "tags": project_doc.get("tags", ["game", "canvas"]),
            "created_at": now_iso,
            "updated_at": now_iso,
            "views": 0,
            "plays": 0
        })
        
    game_names = [g.get("title", g.get("slug")) for g in created_games]
    await profiles_col.update_one(
        {"user_id": user_id_int},
        {"$set": {"created_games": created_games, "game_names": game_names, "updated_at": now}}
    )
    return True

async def remove_project_from_profile(user_id: int, slug: str) -> bool:
    """Removes a game entry and updates game_names in studio_profiles when a project is deleted."""
    if profiles_col is None:
        return False
    user_id_int = int(user_id)
    safe_slug = re.sub(r'[^a-zA-Z0-9_-]', '', slug).lower()
    now = datetime.now(timezone.utc)
    
    profile = await profiles_col.find_one({"user_id": user_id_int})
    if profile:
        created_games = [g for g in profile.get("created_games", []) if g.get("slug") != safe_slug]
        game_names = [g.get("title", g.get("slug")) for g in created_games]
        await profiles_col.update_one(
            {"user_id": user_id_int},
            {"$set": {"created_games": created_games, "game_names": game_names, "updated_at": now}}
        )
        return True
    return False

async def save_user_api_key(user_id: int, api_key: str, username: str = None) -> dict:
    """
    Validates, duplicate-checks, and saves a user's personal Google AI Studio API key.
    Sensitive data: NEVER exposed in frontend responses.
    """
    if users_col is None:
        return {"success": False, "error": "Database not connected."}
        
    cleaned_key = api_key.strip()
    user_id_int = int(user_id)
    
    # 1. Duplicate check: ensure key is not already registered by a DIFFERENT user
    existing = await users_col.find_one({
        "studio_api_key": cleaned_key,
        "user_id": {"$ne": user_id_int}
    })
    if existing:
        return {
            "success": False, 
            "error": "This Google AI Studio API key is already registered to another user account. Please use your own unique key from Google AI Studio."
        }
    
    # 2. Live verification check with Google AI Studio
    is_valid, verify_msg = await verify_google_ai_studio_key(cleaned_key)
    if not is_valid:
        return {
            "success": False, 
            "error": verify_msg or "Invalid Google AI Studio API key. Google AI Studio rejected the key."
        }
        
    # 3. Save key and accepted terms in user profile
    now = datetime.now(timezone.utc)
    update_data = {
        "studio_api_key": cleaned_key,
        "studio_terms_accepted": True,
        "studio_terms_accepted_at": now,
        "updated_at": now
    }
    if username:
        update_data["username"] = username

    await users_col.update_one(
        {"user_id": user_id_int},
        {"$set": update_data},
        upsert=True
    )
    return {"success": True, "message": "API key verified and saved."}

async def list_user_projects(user_id: int):
    """Lists all projects owned by a specific user."""
    if projects_col is None:
        return []
    cursor = projects_col.find({"user_id": int(user_id)}).sort("updated_at", -1)
    projects = await cursor.to_list(length=100)
    for p in projects:
        p["_id"] = str(p["_id"])
    return projects

async def get_project(user_id: int, slug: str):
    """Fetches a specific project by user and slug."""
    if projects_col is None:
        return None
    proj = await projects_col.find_one({"user_id": int(user_id), "slug": slug})
    if proj:
        proj["_id"] = str(proj["_id"])
    return proj

async def get_project_by_username_and_slug(username: str, slug: str):
    """Fetches a project by author username and slug."""
    if projects_col is None:
        return None
    proj = await projects_col.find_one({"username": username.lower(), "slug": slug.lower()})
    if proj:
        proj["_id"] = str(proj["_id"])
    return proj

async def get_project_by_spectator_token(token: str):
    """Fetches a project by unique spectator token."""
    if projects_col is None or not token:
        return None
    proj = await projects_col.find_one({"spectator_token": token})
    if proj:
        proj["_id"] = str(proj["_id"])
    return proj

async def save_project(
    user_id: int, 
    username: str, 
    slug: str, 
    title: str, 
    description: str = "", 
    files: list = None, 
    tags: list = None,
    is_public: bool = True
):
    """Creates or updates a project in the database."""
    if projects_col is None:
        return None
        
    safe_slug = re.sub(r'[^a-zA-Z0-9_-]', '', slug).lower()
    now = datetime.now(timezone.utc)
    
    # Ensure a spectator token exists
    existing = await projects_col.find_one({"user_id": int(user_id), "slug": safe_slug})
    spectator_token = (existing.get("spectator_token") if existing else None) or secrets.token_urlsafe(16)
    
    project_doc = {
        "user_id": int(user_id),
        "username": username.lower(),
        "slug": safe_slug,
        "title": title,
        "description": description or f"A game created by {username} with Yulya Studio.",
        "tags": tags or ["game", "canvas", "html5"],
        "is_public": is_public,
        "spectator_token": spectator_token,
        "updated_at": now
    }
    
    await projects_col.update_one(
        {"user_id": int(user_id), "slug": safe_slug},
        {"$set": project_doc, "$setOnInsert": {"created_at": now}},
        upsert=True
    )
    # Sync to studio_profiles collection
    try:
        await sync_project_to_profile(user_id, username, project_doc)
    except Exception as e:
        print(f"[DATABASE] Profile sync error: {e}")
        
    return project_doc

async def delete_project(user_id: int, slug: str):
    """Deletes a project record from database."""
    if projects_col is None:
        return False
    safe_slug = re.sub(r'[^a-zA-Z0-9_-]', '', slug).lower()
    res = await projects_col.delete_one({"user_id": int(user_id), "slug": safe_slug})
    # Remove from studio_profiles collection
    try:
        await remove_project_from_profile(user_id, safe_slug)
    except Exception as e:
        print(f"[DATABASE] Profile remove error: {e}")
    return res.deleted_count > 0

async def list_community_arcade(limit: int = 50):
    """Lists recent public projects for the Arcade Gallery from studio_profiles and projects_col."""
    games = []
    seen = set()
    
    # 1. Read games from studio_profiles
    if profiles_col is not None:
        try:
            cursor = profiles_col.find({"created_games": {"$exists": True, "$not": {"$size": 0}}}).sort("updated_at", -1).limit(limit)
            profs = await cursor.to_list(length=limit)
            for prof in profs:
                u = prof.get("username") or prof.get("login_id", "creator")
                for g in prof.get("created_games", []):
                    s = g.get("slug")
                    if not s:
                        continue
                    key = f"{u}/{s}"
                    if key not in seen:
                        seen.add(key)
                        games.append({
                            "username": u,
                            "slug": s,
                            "title": g.get("title") or s,
                            "description": g.get("description", ""),
                            "tags": g.get("tags", ["game", "canvas"]),
                            "spectator_token": g.get("spectator_token", ""),
                            "created_at": g.get("created_at", ""),
                            "updated_at": g.get("updated_at", "")
                        })
        except Exception as e:
            print(f"[COMMUNITY] Profile fetch error: {e}")

    # 2. Fallback to projects_col
    if len(games) < limit and projects_col is not None:
        try:
            cursor = projects_col.find({"is_public": {"$ne": False}}).sort("updated_at", -1).limit(limit)
            projects = await cursor.to_list(length=limit)
            for p in projects:
                u = p.get("username", "creator")
                s = p.get("slug", "")
                key = f"{u}/{s}"
                if key not in seen:
                    seen.add(key)
                    games.append({
                        "username": u,
                        "slug": s,
                        "title": p.get("title") or s,
                        "description": p.get("description", ""),
                        "tags": p.get("tags", ["game", "canvas"]),
                        "spectator_token": p.get("spectator_token", ""),
                        "created_at": str(p.get("created_at", "")),
                        "updated_at": str(p.get("updated_at", ""))
                    })
        except Exception:
            pass

    return games[:limit]

# --- Studio Signals for Decoupled Bot Communication (Section 108) ---

async def send_studio_signal(signal_type: str, user_id: int, payload: dict = None):
    """
    Writes a signal to MongoDB studio_signals for the Discord Bot service to act upon.
    Used for graceful Leave VC, session termination, etc.
    """
    if signals_col is None:
        return False
    now = datetime.now(timezone.utc)
    doc = {
        "type": signal_type,
        "user_id": int(user_id),
        "payload": payload or {},
        "created_at_dt": now,
        "processed": False
    }
    await signals_col.insert_one(doc)
    return True

# --- Sessions Persistence ---

async def get_session(token: str):
    if sessions_col is None or not token:
        return None
    return await sessions_col.find_one({"token": token})

async def save_session(token: str, user_data: dict):
    if sessions_col is None or not token:
        return False
    now = datetime.now(timezone.utc)
    doc = {
        "token": token,
        "user": user_data,
        "created_at": now.timestamp(),
        "created_at_dt": now
    }
    await sessions_col.update_one({"token": token}, {"$set": doc}, upsert=True)
    return True

async def delete_session(token: str):
    if sessions_col is None or not token:
        return False
    await sessions_col.delete_one({"token": token})
    return True
