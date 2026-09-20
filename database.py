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
projects_col = None
sessions_col = None
signals_col = None

async def init_db():
    global db_client, db, users_col, projects_col, sessions_col, signals_col
    if not config.MONGO_URI:
        print("[DATABASE] Warning: MONGO_URI not configured!")
        return False
    
    try:
        db_client = AsyncIOMotorClient(config.MONGO_URI, maxIdleTimeMS=60000)
        db = db_client['yulya_bot_db']
        users_col = db['user_profiles']
        projects_col = db['studio_projects']
        sessions_col = db['studio_sessions']
        signals_col = db['studio_signals']
        
        # 1. Projects indexes
        await projects_col.create_index([("user_id", 1), ("slug", 1)], unique=True)
        await projects_col.create_index([("updated_at", -1)])
        await projects_col.create_index([("spectator_token", 1)], sparse=True)
        
        # 2. Sessions indexes (TTL: 30 days)
        await sessions_col.create_index([("token", 1)], unique=True)
        try:
            await sessions_col.create_index([("created_at_dt", 1)], expireAfterSeconds=86400 * 30)
        except Exception:
            pass

        # 3. Signals index (TTL: 10 minutes)
        try:
            await signals_col.create_index([("created_at_dt", 1)], expireAfterSeconds=600)
        except Exception:
            pass

        print("[DATABASE] Connected to MongoDB (yulya_bot_db) successfully.")
        return True
    except Exception as e:
        print(f"[DATABASE] Connection error: {e}")
        return False

async def verify_gemini_api_key(api_key: str) -> tuple[bool, str]:
    """
    Verifies that the provided Gemini API key is valid by sending a minimal ping request.
    Returns (is_valid, message).
    """
    if not api_key or not isinstance(api_key, str) or len(api_key.strip()) < 15:
        return False, "API key is too short or invalid format."
    
    cleaned_key = api_key.strip()
    try:
        def _test_call():
            client = genai.Client(api_key=cleaned_key)
            resp = client.models.generate_content(
                model="gemini-2.5-flash",
                contents="ping"
            )
            return resp and hasattr(resp, 'text')
            
        success = await asyncio.to_thread(_test_call)
        if success:
            return True, "API key verified successfully."
        return False, "No response from Gemini verification ping."
    except APIError as ae:
        # Check specific error details
        msg = str(ae)
        if "API_KEY_INVALID" in msg or "not valid" in msg.lower() or ae.code in [400, 403]:
            return False, "This Gemini API key could not be verified by Google AI Studio. Please check the key and try again."
        elif "RESOURCE_EXHAUSTED" in msg or ae.code == 429:
            # Key is valid but quota exceeded
            return True, "Key is valid, though current quota limit is reached."
        return False, f"Google AI verification returned: {msg[:120]}"
    except Exception as e:
        err_str = str(e)
        if "API_KEY_INVALID" in err_str or "not valid" in err_str.lower():
            return False, "This Gemini API key could not be verified. Check the key and try again."
        return False, f"Verification failed: {err_str[:100]}"

async def get_user_profile(user_id: int):
    """Retrieves a user profile by Discord User ID."""
    if users_col is None:
        return None
    return await users_col.find_one({"user_id": int(user_id)})

async def save_user_api_key(user_id: int, api_key: str, username: str = None) -> dict:
    """
    Validates, duplicate-checks, and saves a user's personal Gemini API key.
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
            "error": "This Gemini API key is already registered to another user account. Please use your own unique key from Google AI Studio."
        }
    
    # 2. Live verification check with Google AI Studio
    is_valid, verify_msg = await verify_gemini_api_key(cleaned_key)
    if not is_valid:
        return {
            "success": False,
            "error": verify_msg or "Invalid API key. Google AI Studio rejected the key."
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
        "files": files or ["index.html", "style.css", "app.js"],
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
    return project_doc

async def delete_project(user_id: int, slug: str):
    """Deletes a project record from database."""
    if projects_col is None:
        return False
    safe_slug = re.sub(r'[^a-zA-Z0-9_-]', '', slug).lower()
    res = await projects_col.delete_one({"user_id": int(user_id), "slug": safe_slug})
    return res.deleted_count > 0

async def list_community_arcade(limit: int = 50):
    """Lists recent public projects for the Arcade Gallery."""
    if projects_col is None:
        return []
    cursor = projects_col.find({"is_public": {"$ne": False}}).sort("updated_at", -1).limit(limit)
    projects = await cursor.to_list(length=limit)
    for p in projects:
        p["_id"] = str(p["_id"])
    return projects

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
