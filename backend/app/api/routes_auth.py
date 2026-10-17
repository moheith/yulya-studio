"""
Discord OAuth2 and Session Authentication routes for Yulya Studio V2.
Follows Section 36 of Master Prompt.
"""

import httpx
from typing import Optional
from fastapi import APIRouter, Request, Response, Depends, Query
from fastapi.responses import RedirectResponse, JSONResponse

from backend.app.core.config import settings
from backend.app.core.security import generate_session_token, enforce_rate_limit
from backend.app.core.errors import AppError, ErrorCategory
from backend.app.core.logging import logger
from backend.app.database import repositories

router = APIRouter(prefix="", tags=["Auth"])


import secrets

async def get_current_user(request: Request) -> Optional[dict]:
    """
    Dependency for extracting authenticated user strictly from HttpOnly session cookie.
    Query parameter tokens are rejected to prevent token leakage in URLs and browser histories.
    """
    token = request.cookies.get(settings.COOKIE_NAME)
    if not token:
        return None

    session_doc = await repositories.get_session(token)
    if not session_doc:
        return None
    return session_doc.get("user")


async def require_auth(user: Optional[dict] = Depends(get_current_user)) -> dict:
    """Dependency that enforces active authentication."""
    if not user:
        raise AppError(ErrorCategory.AUTHENTICATION, "Authentication required. Please sign in.", status_code=401)
    return user


@router.get("/auth/login")
async def handle_login():
    """
    Redirects user to Discord OAuth2 authorization with cryptographically secure state
    parameter for anti-CSRF protection.
    """
    if not settings.DISCORD_CLIENT_ID:
        # Mock/dev login fallback if Discord Client ID is not configured
        return RedirectResponse(url="/")

    # Generate one-time OAuth state
    oauth_state = secrets.token_urlsafe(32)
    oauth_url = f"{settings.discord_oauth_url}&state={oauth_state}"
    resp = RedirectResponse(url=oauth_url, status_code=302)
    resp.set_cookie(
        key="yulya_oauth_state",
        value=oauth_state,
        max_age=600,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite="lax",
        path="/"
    )
    return resp


@router.get("/auth/callback")
async def handle_auth_callback(
    request: Request,
    code: Optional[str] = Query(None),
    state: Optional[str] = Query(None)
):
    """
    Handles OAuth2 code exchange with Discord API with strict state validation
    and immediate single-use consumption.
    """
    if not code:
        return RedirectResponse(url="/")

    # Anti-CSRF OAuth State Validation
    cookie_state = request.cookies.get("yulya_oauth_state")
    if not cookie_state or not state or cookie_state != state:
        logger.warning("[AUTH] OAuth state validation failed or expired. Aborting authentication.")
        raise AppError(
            ErrorCategory.AUTHENTICATION,
            "Invalid or expired OAuth state parameter (anti-CSRF validation failed).",
            status_code=403
        )

    enforce_rate_limit("auth_callback", "global", max_req=20, window_sec=60)

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            token_resp = await client.post(
                "https://discord.com/api/oauth2/token",
                data={
                    "client_id": settings.DISCORD_CLIENT_ID,
                    "client_secret": settings.DISCORD_CLIENT_SECRET,
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": f"{settings.BASE_URL}/auth/callback",
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"}
            )
            token_data = token_resp.json()
            access_token = token_data.get("access_token")
            if not access_token:
                return RedirectResponse(url="/?error=oauth_failed")

            # Fetch user info
            user_resp = await client.get(
                "https://discord.com/api/users/@me",
                headers={"Authorization": f"Bearer {access_token}"}
            )
            discord_user = user_resp.json()

        user_id = int(discord_user["id"])
        username = discord_user.get("username", "user")
        avatar = discord_user.get("avatar")

        # Save or update studio profile
        await repositories.save_or_update_profile(
            user_id=user_id,
            username=username,
            avatar=avatar
        )

        # Create session
        token = generate_session_token()
        user_dict = {
            "id": user_id,
            "username": username,
            "avatar": avatar
        }
        await repositories.save_session(token, user_dict)

        resp = RedirectResponse(url="/studio", status_code=302)
        resp.set_cookie(
            key=settings.COOKIE_NAME,
            value=token,
            max_age=86400 * 30,
            httponly=True,
            secure=settings.COOKIE_SECURE,
            samesite="lax",
            path="/"
        )
        resp.delete_cookie(key="yulya_oauth_state", path="/")
        return resp

    except Exception as e:
        return RedirectResponse(url="/?error=auth_error")


@router.get("/auth/logout")
async def handle_logout(request: Request):
    """Logs out user and clears session."""
    token = request.cookies.get(settings.COOKIE_NAME)
    if token:
        await repositories.delete_session(token)
    resp = RedirectResponse(url="/", status_code=302)
    resp.delete_cookie(key=settings.COOKIE_NAME, path="/")
    return resp


@router.get("/api/me")
@router.get("/api/auth/me")
async def api_get_me(user: Optional[dict] = Depends(get_current_user)):
    """Returns currently authenticated user profile without sensitive credentials."""
    if not user:
        return {"authenticated": False, "user": None}

    profile = await repositories.get_profile_by_user_id(user["id"])
    has_api_key = False
    user_db = await repositories.get_user_profile(user["id"])
    if user_db and user_db.get("studio_api_key"):
        has_api_key = True

    return {
        "authenticated": True,
        "user": user,
        "profile": profile,
        "has_api_key": has_api_key
    }


@router.get("/auth/dev-login")
async def handle_dev_login(request: Request, user_id: int = 99999, username: str = "adithya"):
    """Development mode one-click login for local testing."""
    if settings.ENVIRONMENT != "development":
        raise AppError(ErrorCategory.PERMISSION_DENIED, "Dev login only available in development environment.", status_code=403)
    
    token = generate_session_token()
    user_dict = {
        "id": user_id,
        "username": username,
        "display_name": "Adithya",
        "avatar": None
    }
    await repositories.save_or_update_profile(user_id=user_id, username=username)
    await repositories.save_session(token, user_dict)
    
    resp = RedirectResponse(url="/studio", status_code=302)
    resp.set_cookie(
        key=settings.COOKIE_NAME,
        value=token,
        max_age=86400 * 30,
        httponly=True,
        secure=False,
        samesite="lax",
        path="/"
    )
    return resp

