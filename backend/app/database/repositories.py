"""
Database repositories for Yulya Studio V2.
Encapsulates all persistence logic for users, profiles, projects, sessions, and published releases.
"""

import re
import asyncio
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any, Tuple
from google import genai
from google.genai.errors import APIError

from backend.app.database import client
from backend.app.core.security import encrypt_secret, decrypt_secret
from backend.app.core.logging import logger


# --- User API Key Verification ---

async def verify_google_ai_studio_key(api_key: str) -> Tuple[bool, str]:
    """
    Verifies that the provided Google AI Studio API key is valid by sending a minimal ping request.
    Uses fallback cascade across supported lightweight models.
    """
    if not api_key or not isinstance(api_key, str) or len(api_key.strip()) < 15:
        return False, "Google AI Studio API key is too short or invalid format."

    cleaned_key = api_key.strip()

    def _test_call() -> Tuple[bool, str]:
        genai_client = genai.Client(api_key=cleaned_key)
        candidate_models = [
            "gemini-3.5-flash-lite",
            "gemini-3.8-flash",
            "gemini-3.7-flash",
            "gemini-2.5-flash"
        ]
        for model_name in candidate_models:
            try:
                resp = genai_client.models.generate_content(
                    model=model_name,
                    contents="ping"
                )
                if resp and hasattr(resp, "text"):
                    return True, "Google AI Studio API key verified successfully."
            except APIError as ae:
                msg = str(ae)
                if "API_KEY_INVALID" in msg or "not valid" in msg.lower() or ae.code in [400, 403]:
                    return False, "This Google AI Studio API key was rejected by Google AI Studio. Please check the key and try again."
                elif "RESOURCE_EXHAUSTED" in msg or ae.code == 429:
                    return True, "Key is valid, though current quota limit is reached."
                continue
            except Exception as e:
                err_str = str(e)
                if "API_KEY_INVALID" in err_str or "not valid" in err_str.lower():
                    return False, "This Google AI Studio API key could not be verified. Check the key and try again."
                continue
        return False, "Unable to verify API key with Google AI Studio. Please verify the key and try again."

    try:
        return await asyncio.to_thread(_test_call)
    except Exception as e:
        return False, f"Verification failed: {str(e)[:100]}"


# --- User Profiles & Settings ---

async def get_user_profile(user_id: int) -> Optional[Dict[str, Any]]:
    """Retrieves a user profile by Discord User ID."""
    if client.users_col is None:
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

    doc = await client.users_col.find_one({"$or": query_or, "studio_api_key": {"$exists": True, "$ne": ""}})
    if not doc:
        doc = await client.users_col.find_one({"$or": query_or})
    return doc


async def get_decrypted_user_api_key(user_id: int) -> Optional[str]:
    """Retrieves and decrypts the user's stored Google AI Studio API key."""
    profile = await get_user_profile(user_id)
    if not profile:
        return None
    enc_key = profile.get("studio_api_key")
    if not enc_key:
        return None
    return decrypt_secret(enc_key)


async def save_user_api_key(user_id: int, api_key: str, username: Optional[str] = None) -> Dict[str, Any]:
    """
    Validates, encrypts at rest with Fernet, and saves a user's personal Google AI Studio API key.
    Sensitive data: NEVER exposed in frontend responses.
    """
    if client.users_col is None:
        return {"success": False, "error": "Database not connected."}

    cleaned_key = api_key.strip()
    user_id_int = int(user_id)

    # 1. Live verification check with Google AI Studio
    is_valid, verify_msg = await verify_google_ai_studio_key(cleaned_key)
    if not is_valid:
        return {
            "success": False,
            "error": verify_msg or "Invalid Google AI Studio API key."
        }

    # 2. Encrypt key with application-layer encryption (Section 38)
    encrypted_key = encrypt_secret(cleaned_key)

    now = datetime.now(timezone.utc)
    update_data = {
        "studio_api_key": encrypted_key,
        "studio_terms_accepted": True,
        "studio_terms_accepted_at": now,
        "updated_at": now
    }
    if username:
        update_data["username"] = username

    await client.users_col.update_one(
        {"user_id": user_id_int},
        {"$set": update_data},
        upsert=True
    )
    return {"success": True, "message": "API key verified and securely stored."}


async def save_user_preference(user_id: int, key: str, value: Any) -> bool:
    """Saves a user preference (e.g. preferred_live_model, preferred_code_model)."""
    if client.users_col is None:
        return False
    user_id_int = int(user_id)
    now = datetime.now(timezone.utc)
    await client.users_col.update_one(
        {"user_id": user_id_int},
        {"$set": {key: value, "updated_at": now}},
        upsert=True
    )
    return True


async def get_user_preferences(user_id: int) -> Dict[str, Any]:
    """Retrieves server-stored model preferences for a user."""
    profile = await get_user_profile(user_id) or {}
    prefs = {k: v for k, v in profile.items() if k not in ("_id", "password", "salt", "token", "studio_api_key")}
    prefs.setdefault("preferred_live_model", profile.get("preferred_live_model"))
    prefs.setdefault("preferred_code_model", profile.get("preferred_code_model"))
    return prefs


async def get_user_preference(user_id: int, key: str, default: Any = None) -> Any:
    prefs = await get_user_preferences(user_id)
    val = prefs.get(key)
    return val if val is not None else default


# --- Studio Profiles (Public Portfolios) ---

async def save_or_update_profile(
    user_id: int,
    username: str,
    display_name: Optional[str] = None,
    avatar: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    if client.profiles_col is None:
        return None

    user_id_int = int(user_id)
    clean_username = username.strip().lower()
    clean_display = display_name or username
    now = datetime.now(timezone.utc)

    existing = await client.profiles_col.find_one({"user_id": user_id_int})
    if existing:
        update_fields: Dict[str, Any] = {
            "login_id": clean_username,
            "username": clean_username,
            "profile_name": clean_display,
            "display_name": clean_display,
            "updated_at": now
        }
        if avatar is not None:
            update_fields["avatar"] = avatar

        await client.profiles_col.update_one(
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
            "created_games": [],
            "game_names": [],
            "created_at": now,
            "updated_at": now
        }
        res = await client.profiles_col.insert_one(new_profile)
        new_profile["_id"] = str(res.inserted_id)
        return new_profile


async def get_profile_by_user_id(user_id: int) -> Optional[Dict[str, Any]]:
    if client.profiles_col is None:
        return None
    doc = await client.profiles_col.find_one({"user_id": int(user_id)})
    if doc:
        doc["_id"] = str(doc.get("_id", ""))
    return doc


async def get_profile_by_username(username: str) -> Optional[Dict[str, Any]]:
    if client.profiles_col is None:
        return None
    clean = username.strip().lower()
    doc = await client.profiles_col.find_one({"$or": [{"username": clean}, {"login_id": clean}]})
    if doc:
        doc["_id"] = str(doc.get("_id", ""))
    return doc


# --- Studio Projects ---

async def save_project(
    user_id: int,
    username: str,
    slug: str,
    title: str,
    description: str = "",
    files: Optional[List[str]] = None,
    tags: Optional[List[str]] = None,
    is_public: bool = True
) -> Dict[str, Any]:
    if client.projects_col is None:
        raise RuntimeError("Database not initialized")

    user_id_int = int(user_id)
    clean_username = username.strip().lower()
    safe_slug = re.sub(r'[^a-zA-Z0-9_-]', '', slug).lower()
    now = datetime.now(timezone.utc)

    doc = {
        "user_id": user_id_int,
        "username": clean_username,
        "slug": safe_slug,
        "title": title or safe_slug,
        "description": description or "",
        "files": files or ["index.html", "style.css", "app.js"],
        "tags": tags or ["game", "canvas"],
        "is_public": is_public,
        "updated_at": now
    }

    res = await client.projects_col.update_one(
        {"user_id": user_id_int, "slug": safe_slug},
        {"$set": doc, "$setOnInsert": {"created_at": now}},
        upsert=True
    )

    # Sync into studio_profiles portfolio
    await sync_project_to_profile(user_id_int, clean_username, doc)
    return doc


async def sync_project_to_profile(user_id: int, username: str, project_doc: Dict[str, Any]) -> bool:
    if client.profiles_col is None:
        return False
    user_id_int = int(user_id)
    clean_username = username.strip().lower()
    safe_slug = project_doc["slug"]
    game_title = project_doc.get("title", safe_slug)
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()

    profile = await client.profiles_col.find_one({"user_id": user_id_int})
    if not profile:
        await save_or_update_profile(user_id_int, clean_username)
        profile = await client.profiles_col.find_one({"user_id": user_id_int})

    created_games = profile.get("created_games", []) if profile else []
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
    await client.profiles_col.update_one(
        {"user_id": user_id_int},
        {"$set": {"created_games": created_games, "game_names": game_names, "updated_at": now}}
    )
    return True


async def remove_project_from_profile(user_id: int, slug: str) -> bool:
    if client.profiles_col is None:
        return False
    user_id_int = int(user_id)
    safe_slug = re.sub(r'[^a-zA-Z0-9_-]', '', slug).lower()
    now = datetime.now(timezone.utc)

    profile = await client.profiles_col.find_one({"user_id": user_id_int})
    if profile:
        created_games = [g for g in profile.get("created_games", []) if g.get("slug") != safe_slug]
        game_names = [g.get("title", g.get("slug")) for g in created_games]
        await client.profiles_col.update_one(
            {"user_id": user_id_int},
            {"$set": {"created_games": created_games, "game_names": game_names, "updated_at": now}}
        )
        return True
    return False


async def get_project(user_id: int, slug: str) -> Optional[Dict[str, Any]]:
    if client.projects_col is None:
        return None
    safe_slug = re.sub(r'[^a-zA-Z0-9_-]', '', slug).lower()
    doc = await client.projects_col.find_one({"user_id": int(user_id), "slug": safe_slug})
    if doc:
        doc["_id"] = str(doc.get("_id", ""))
    return doc


async def get_project_by_username_and_slug(username: str, slug: str) -> Optional[Dict[str, Any]]:
    if client.projects_col is None:
        return None
    clean_username = username.strip().lower()
    safe_slug = re.sub(r'[^a-zA-Z0-9_-]', '', slug).lower()
    doc = await client.projects_col.find_one({"username": clean_username, "slug": safe_slug})
    if doc:
        doc["_id"] = str(doc.get("_id", ""))
    return doc


async def list_user_projects(user_id: int) -> List[Dict[str, Any]]:
    if client.projects_col is None:
        return []
    cursor = client.projects_col.find({"user_id": int(user_id)}).sort("updated_at", -1)
    results = await cursor.to_list(length=100)
    for r in results:
        r["_id"] = str(r.get("_id", ""))
    return results


async def list_community_projects(limit: int = 50, skip: int = 0) -> List[Dict[str, Any]]:
    if client.projects_col is None:
        return []
    cursor = client.projects_col.find({"is_public": True}).sort("updated_at", -1).skip(skip).limit(limit)
    results = await cursor.to_list(length=limit)
    for r in results:
        r["_id"] = str(r.get("_id", ""))
    return results


async def delete_project(user_id: int, slug: str) -> bool:
    if client.projects_col is None:
        return False
    user_id_int = int(user_id)
    safe_slug = re.sub(r'[^a-zA-Z0-9_-]', '', slug).lower()
    res = await client.projects_col.delete_one({"user_id": user_id_int, "slug": safe_slug})
    await remove_project_from_profile(user_id_int, safe_slug)
    # Also delete published releases
    if client.releases_col is not None:
        await client.releases_col.delete_many({"user_id": user_id_int, "slug": safe_slug})
    return res.deleted_count > 0


# --- Sessions ---

async def save_session(token: str, user_dict: Dict[str, Any]) -> None:
    if client.sessions_col is None:
        return
    now = datetime.now(timezone.utc)
    await client.sessions_col.update_one(
        {"token": token},
        {"$set": {"token": token, "user": user_dict, "created_at": now.timestamp(), "created_at_dt": now}},
        upsert=True
    )


async def get_session(token: str) -> Optional[Dict[str, Any]]:
    if client.sessions_col is None:
        return None
    return await client.sessions_col.find_one({"token": token})


async def delete_session(token: str) -> None:
    if client.sessions_col is None:
        return
    await client.sessions_col.delete_one({"token": token})


# --- Published Releases (Section 59: Separate Drafts vs Public Releases) ---

async def publish_release(
    user_id: int,
    username: str,
    slug: str,
    title: str,
    description: str,
    files: List[str],
    changelog: str = "",
    version: Optional[int] = None,
    file_hashes: Optional[Dict[str, str]] = None,
    total_bytes: int = 0
) -> Dict[str, Any]:
    """Publishes an immutable public release snapshot with verified file hashes."""
    if client.releases_col is None:
        raise RuntimeError("Database not connected")

    user_id_int = int(user_id)
    clean_username = username.strip().lower()
    safe_slug = re.sub(r'[^a-zA-Z0-9_-]', '', slug).lower()
    now = datetime.now(timezone.utc)

    if version is None:
        # Determine next sequential version
        latest = await client.releases_col.find_one(
            {"user_id": user_id_int, "slug": safe_slug},
            sort=[("version", -1)]
        )
        version = (latest.get("version", 0) + 1) if latest else 1

    # Mark prior releases inactive
    await client.releases_col.update_many(
        {"user_id": user_id_int, "slug": safe_slug},
        {"$set": {"is_active": False}}
    )

    release_doc = {
        "user_id": user_id_int,
        "username": clean_username,
        "slug": safe_slug,
        "title": title,
        "description": description,
        "version": version,
        "files": files,
        "file_hashes": file_hashes or {},
        "total_bytes": total_bytes,
        "changelog": changelog,
        "is_active": True,
        "published_at": now
    }
    await client.releases_col.insert_one(release_doc)
    release_doc["_id"] = str(release_doc.get("_id", ""))
    return release_doc


async def rollback_release(user_id: int, slug: str, target_version: int) -> Optional[Dict[str, Any]]:
    """Rolls back the active release to an existing historical version."""
    if client.releases_col is None:
        return None
    user_id_int = int(user_id)
    safe_slug = re.sub(r'[^a-zA-Z0-9_-]', '', slug).lower()

    target = await client.releases_col.find_one({"user_id": user_id_int, "slug": safe_slug, "version": target_version})
    if not target:
        return None

    # Deactivate all versions
    await client.releases_col.update_many(
        {"user_id": user_id_int, "slug": safe_slug},
        {"$set": {"is_active": False}}
    )
    # Activate target
    await client.releases_col.update_one(
        {"_id": target["_id"]},
        {"$set": {"is_active": True}}
    )
    target["is_active"] = True
    target["_id"] = str(target["_id"])
    return target


async def get_release_by_version(user_id: int, slug: str, version: int) -> Optional[Dict[str, Any]]:
    """Retrieves a specific historical release version."""
    if client.releases_col is None:
        return None
    user_id_int = int(user_id)
    safe_slug = re.sub(r'[^a-zA-Z0-9_-]', '', slug).lower()
    doc = await client.releases_col.find_one({"user_id": user_id_int, "slug": safe_slug, "version": version})
    if doc:
        doc["_id"] = str(doc.get("_id", ""))
    return doc


async def get_active_release(username: str, slug: str) -> Optional[Dict[str, Any]]:
    """Retrieves the active published release for a game."""
    if client.releases_col is None:
        return None
    clean_username = username.strip().lower()
    safe_slug = re.sub(r'[^a-zA-Z0-9_-]', '', slug).lower()
    doc = await client.releases_col.find_one({"username": clean_username, "slug": safe_slug, "is_active": True})
    if doc:
        doc["_id"] = str(doc.get("_id", ""))
    return doc


async def list_releases(user_id: int, slug: str) -> List[Dict[str, Any]]:
    if client.releases_col is None:
        return []
    safe_slug = re.sub(r'[^a-zA-Z0-9_-]', '', slug).lower()
    cursor = client.releases_col.find({"user_id": int(user_id), "slug": safe_slug}).sort("version", -1)
    results = await cursor.to_list(length=50)
    for r in results:
        r["_id"] = str(r.get("_id", ""))
    return results
