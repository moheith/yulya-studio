"""
Core configuration for Yulya Studio V2.
Uses pydantic-settings for robust environment variable loading, validation, and type safety.
"""

import os
from pathlib import Path
from typing import Optional, Set
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # Server & Network
    PORT: int = 10000
    HOST: str = "0.0.0.0"
    BASE_URL: str = "https://project.yulya.me"
    SESSION_SECRET: str = "yulya_studio_secret_key_2026_super_secure"
    COOKIE_NAME: str = "yulya_studio_session"
    COOKIE_SECURE: bool = False  # Set dynamically in model_post_init or based on BASE_URL

    # Database
    MONGO_URI: Optional[str] = None
    TEST_MONGO_URI: Optional[str] = None
    MONGO_DB_NAME: str = "yulya_bot_db"
    TEST_MONGO_DB_NAME: str = "yulya_test_db"

    # Discord Identity Provider (OAuth2)
    DISCORD_CLIENT_ID: Optional[str] = None
    DISCORD_CLIENT_SECRET: Optional[str] = None

    # Paths
    BASE_DIR: Path = Path(__file__).resolve().parent.parent.parent.parent
    DATA_DIR: Path = Path(__file__).resolve().parent.parent.parent.parent / "data"
    PROJECTS_DIR: Path = Path(__file__).resolve().parent.parent.parent.parent / "data" / "projects"
    STATIC_DIR: Path = Path(__file__).resolve().parent.parent.parent.parent / "static"
    FRONTEND_DIST_DIR: Path = Path(__file__).resolve().parent.parent.parent.parent / "frontend" / "dist"

    # Resource & File Boundaries (Section 28)
    MAX_FILE_SIZE: int = 5 * 1024 * 1024           # 5 MiB per file
    MAX_PROJECT_SIZE: int = 50 * 1024 * 1024       # 50 MiB total project size
    MAX_TEXT_SOURCE_SIZE: int = 1 * 1024 * 1024    # 1 MiB for code files
    MAX_NESTED_PATH_DEPTH: int = 12                # Max path depth
    MAX_FILES_PER_PROJECT: int = 500               # Max files count
    MAX_BUILDS_PER_PROJECT: int = 1                # 1 active build lock per project
    MAX_BUILDS_PER_USER: int = 2                   # Max concurrent builds per user
    MAX_SYSTEM_CONCURRENT_BUILDS: int = 5          # System-wide concurrent build cap
    MAX_BUILD_DURATION_SEC: int = 240              # 4 min timeout for builds
    MAX_TOOL_TIMEOUT_SEC: int = 30                 # 30 sec timeout for tool execution
    MAX_LIVE_CONNECT_TIMEOUT_SEC: float = 10.0     # 10s timeout on Live handshake

    # Visual Observation / Screenshare Limits
    SCREENSHOT_MAX_FPS: float = 1.0                # ~1 frame per second
    SCREENSHOT_MAX_BYTES: int = 512 * 1024         # 512 KiB per frame

    # Rate Limits: (max_requests, window_seconds)
    RATE_LIMIT_MODIFY: tuple[int, int] = (10, 60)
    RATE_LIMIT_SAVE_KEY: tuple[int, int] = (5, 60)
    RATE_LIMIT_CREATE: tuple[int, int] = (5, 60)
    RATE_LIMIT_PUBLISH: tuple[int, int] = (10, 60)

    # Allowed Game File Extensions (Section 27)
    ALLOWED_GAME_EXTENSIONS: Set[str] = {
        ".html", ".css", ".js", ".mjs", ".json", ".svg",
        ".png", ".jpg", ".jpeg", ".webp", ".avif", ".gif",
        ".mp3", ".wav", ".ogg", ".mp4", ".webm",
        ".woff", ".woff2", ".gltf", ".glb", ".obj", ".mtl", ".bin"
    }

    # Strictly Disallowed Files & System Patterns
    DISALLOWED_EXTENSIONS: Set[str] = {
        ".py", ".pyc", ".sh", ".bash", ".bat", ".cmd", ".ps1",
        ".exe", ".env", ".dll", ".so", ".dylib", ".wasm_unapproved"
    }

    PROTECTED_FILENAMES: Set[str] = {
        ".env", ".gitignore", "server.py", "config.py", "database.py",
        "requirements.txt", "Procfile", "build.log", "package.json", "tsconfig.json"
    }

    def model_post_init(self, __context):
        self.BASE_URL = self.BASE_URL.rstrip("/")
        if self.BASE_URL.startswith("https://"):
            self.COOKIE_SECURE = True
        self.PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
        self.STATIC_DIR.mkdir(parents=True, exist_ok=True)

    @property
    def discord_oauth_url(self) -> str:
        return (
            f"https://discord.com/api/oauth2/authorize?client_id={self.DISCORD_CLIENT_ID}"
            f"&redirect_uri={self.BASE_URL}/auth/callback&response_type=code&scope=identify"
        )


settings = Settings()
