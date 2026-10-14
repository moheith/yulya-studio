"""
Database Client & Connection Manager with strict test isolation for Yulya Studio V2.
Enforces P0 safety guarantees: tests will NEVER touch production MongoDB Atlas.
"""

from typing import Optional
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase, AsyncIOMotorCollection
from backend.app.core.config import settings
from backend.app.core.logging import logger

db_client: Optional[AsyncIOMotorClient] = None
db: Optional[AsyncIOMotorDatabase] = None

# Collections
users_col: Optional[AsyncIOMotorCollection] = None
profiles_col: Optional[AsyncIOMotorCollection] = None
projects_col: Optional[AsyncIOMotorCollection] = None
sessions_col: Optional[AsyncIOMotorCollection] = None
releases_col: Optional[AsyncIOMotorCollection] = None


async def init_db(
    uri: Optional[str] = None,
    db_name: Optional[str] = None,
    create_indexes: bool = True,
    is_test: bool = False
) -> bool:
    """
    Initializes the asynchronous MongoDB connection.
    Enforces strict test database isolation:
    If is_test is True, TEST_MONGO_URI is required and target database CANNOT be yulya_bot_db.
    """
    global db_client, db, users_col, profiles_col, projects_col, sessions_col, releases_col

    if is_test:
        test_uri = uri or settings.TEST_MONGO_URI
        if not test_uri:
            raise RuntimeError(
                "[DATABASE TEST ISOLATION] Refusing to run tests: TEST_MONGO_URI is not set. "
                "Tests must NEVER run against production MongoDB!"
            )
        target_db_name = db_name or settings.TEST_MONGO_DB_NAME
        if target_db_name == "yulya_bot_db":
            raise RuntimeError(
                "[DATABASE TEST ISOLATION] Refusing to run tests: Test database name cannot be 'yulya_bot_db'!"
            )
        target_uri = test_uri
    else:
        target_uri = uri or settings.MONGO_URI
        target_db_name = db_name or settings.MONGO_DB_NAME

    if not target_uri:
        logger.warning("[DATABASE] Warning: MONGO_URI not configured. Running in memory / offline mode.")
        return False

    try:
        db_client = AsyncIOMotorClient(target_uri, maxIdleTimeMS=60000)
        db = db_client[target_db_name]
        users_col = db["user_profiles"]
        profiles_col = db["studio_profiles"]
        projects_col = db["studio_projects"]
        sessions_col = db["studio_sessions"]
        releases_col = db["studio_releases"]

        if create_indexes:
            # 1. Studio Profiles indexes
            await profiles_col.create_index([("user_id", 1)], unique=True)
            await profiles_col.create_index([("username", 1)])

            # 2. Projects indexes
            await projects_col.create_index([("user_id", 1), ("slug", 1)], unique=True)
            await projects_col.create_index([("updated_at", -1)])

            # 3. Sessions indexes (TTL: 30 days)
            await sessions_col.create_index([("token", 1)], unique=True)
            try:
                await sessions_col.create_index([("created_at_dt", 1)], expireAfterSeconds=86400 * 30)
            except Exception:
                pass

            # 4. Published Releases indexes
            await releases_col.create_index([("user_id", 1), ("slug", 1), ("version", 1)], unique=True)
            await releases_col.create_index([("slug", 1), ("is_active", 1)])
            await releases_col.create_index([("published_at", -1)])

        logger.info(f"[DATABASE] Connected to MongoDB ({target_db_name}) successfully.")
        return True
    except Exception as e:
        logger.error(f"[DATABASE] Connection error: {e}")
        return False


async def close_db() -> None:
    """Closes the MongoDB client connection cleanly."""
    global db_client, db
    if db_client:
        db_client.close()
        db_client = None
        db = None
