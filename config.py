import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
PROJECTS_DIR = BASE_DIR / "data" / "projects"
STATIC_DIR = BASE_DIR / "static"
TEMPLATES_DIR = BASE_DIR / "templates"

PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
STATIC_DIR.mkdir(exist_ok=True)
TEMPLATES_DIR.mkdir(exist_ok=True)

PORT = int(os.getenv("PORT", 10000))
MONGO_URI = os.getenv("MONGO_URI")
DISCORD_CLIENT_ID = os.getenv("DISCORD_CLIENT_ID")
DISCORD_CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET")
BASE_URL = os.getenv("BASE_URL", "https://project.yulya.me").rstrip("/")
SESSION_SECRET = os.getenv("SESSION_SECRET", "yulya_studio_secret_key_2026_super_secure")

COOKIE_NAME = "yulya_studio_session"
COOKIE_SECURE = BASE_URL.startswith("https")

# File size limits (Section 31 & Multi-File Architecture)
MAX_FILE_SIZE = 5 * 1024 * 1024       # 5 MB per file
MAX_PROJECT_SIZE = 20 * 1024 * 1024   # 20 MB total project size

# Rate limits: (max_requests, window_seconds) (Section 30)
RATE_LIMIT_MODIFY = (10, 60)
RATE_LIMIT_SAVE_KEY = (5, 60)
RATE_LIMIT_CREATE = (5, 60)

DISCORD_OAUTH_URL = (
    f"https://discord.com/api/oauth2/authorize?client_id={DISCORD_CLIENT_ID}"
    f"&redirect_uri={BASE_URL}/auth/callback&response_type=code&scope=identify"
)
