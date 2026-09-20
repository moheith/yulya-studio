import os
import re
import asyncio
from datetime import datetime, timezone
from motor.motor_asyncio import AsyncIOMotorClient
from google import genai
import config

db_client = None
db = None
users_col = None
projects_col = None

async def init_db():
    global db_client, db, users_col, projects_col
    if not config.MONGO_URI:
        print("[DATABASE] Warning: MONGO_URI not configured!")
        return False
    
    db_client = AsyncIOMotorClient(config.MONGO_URI, maxIdleTimeMS=60000)
    db = db_client['yulya_bot_db']
    users_col = db['user_profiles']
    projects_col = db['studio_projects']
    
    # Create indexes for fast lookup and uniqueness
    await projects_col.create_index([("user_id", 1), ("slug", 1)], unique=True)
    await projects_col.create_index([("updated_at", -1)])
    print("[DATABASE] Connected to MongoDB (yulya_bot_db) successfully.")
    return True

async def verify_gemini_api_key(api_key: str) -> bool:
    """Verifies that the provided Gemini API key is valid by sending a tiny ping request."""
    if not api_key or not isinstance(api_key, str) or len(api_key.strip()) < 15:
        return False
    
    cleaned_key = api_key.strip()
    try:
        # Run synchronous client in threadpool so it does not block the async event loop
        def _test_call():
            client = genai.Client(api_key=cleaned_key)
            resp = client.models.generate_content(
                model="gemini-2.5-flash",
                contents="ping"
            )
            return resp and hasattr(resp, 'text')
            
        return await asyncio.to_thread(_test_call)
    except Exception as e:
        print(f"[DATABASE] Gemini key verification failed: {e}")
        return False

async def get_user_profile(user_id: int):
    """Retrieves a user profile by Discord User ID."""
    if users_col is None:
        return None
    return await users_col.find_one({"user_id": int(user_id)})

async def save_user_api_key(user_id: int, api_key: str, username: str = None) -> dict:
    """
    Validates, duplicate-checks, and saves a user's personal Gemini API key.
    """
    if users_col is None:
        return {"success": False, "error": "Database not connected."}
        
    cleaned_key = api_key.strip()
    user_id_int = int(user_id)
    
    # 1. Duplicate check: ensure key is not already in use by another user
    existing = await users_col.find_one({
        "studio_api_key": cleaned_key,
        "user_id": {"$ne": user_id_int}
    })
    if existing:
        return {
            "success": False, 
            "error": "This Gemini API key is already registered to another user account. Please use your own unique key."
        }
    
    # 2. Live verification check: ensure key actually works
    is_valid = await verify_gemini_api_key(cleaned_key)
    if not is_valid:
        return {
            "success": False,
            "error": "Invalid API key! Google AI Studio rejected the key. Please verify and paste a valid Gemini API key."
        }
        
    # 3. Save key and accepted terms in user profile
    update_data = {
        "studio_api_key": cleaned_key,
        "studio_terms_accepted": True,
        "studio_terms_accepted_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc)
    }
    if username:
        update_data["username"] = username

    await users_col.update_one(
        {"user_id": user_id_int},
        {"$set": update_data},
        upsert=True
    )
    return {"success": True}

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
    proj = await projects_col.find_one({"username": username.lower(), "slug": slug})
    if proj:
        proj["_id"] = str(proj["_id"])
    return proj

async def save_project(user_id: int, username: str, slug: str, title: str, description: str = "", files: list = None, tags: list = None):
    """Creates or updates a project in the database."""
    if projects_col is None:
        return None
        
    safe_slug = re.sub(r'[^a-zA-Z0-9_-]', '', slug).lower()
    now = datetime.now(timezone.utc)
    
    project_doc = {
        "user_id": int(user_id),
        "username": username.lower(),
        "slug": safe_slug,
        "title": title,
        "description": description or f"A game created by {username} with Yulya Studio.",
        "files": files or ["index.html", "style.css", "app.js"],
        "tags": tags or ["game", "canvas", "interactive"],
        "updated_at": now
    }
    
    await projects_col.update_one(
        {"user_id": int(user_id), "slug": safe_slug},
        {"$set": project_doc, "$setOnInsert": {"created_at": now}},
        upsert=True
    )
    return project_doc

async def rename_project(user_id: int, old_slug: str, new_title: str, new_slug: str):
    """Renames a project title and slug."""
    if projects_col is None:
        return False
    safe_new_slug = re.sub(r'[^a-zA-Z0-9_-]', '', new_slug).lower()
    now = datetime.now(timezone.utc)
    
    res = await projects_col.update_one(
        {"user_id": int(user_id), "slug": old_slug},
        {"$set": {
            "title": new_title,
            "slug": safe_new_slug,
            "updated_at": now
        }}
    )
    return res.modified_count > 0

async def delete_project(user_id: int, slug: str):
    """Deletes a project record from database."""
    if projects_col is None:
        return False
    res = await projects_col.delete_one({"user_id": int(user_id), "slug": slug})
    return res.deleted_count > 0

async def list_community_arcade(limit: int = 50):
    """Lists recent projects for the public Arcade Gallery."""
    if projects_col is None:
        return []
    cursor = projects_col.find().sort("updated_at", -1).limit(limit)
    projects = await cursor.to_list(length=limit)
    for p in projects:
        p["_id"] = str(p["_id"])
    return projects
