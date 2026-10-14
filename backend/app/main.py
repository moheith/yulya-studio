"""
FastAPI Application Entrypoint for Yulya Studio V2.
Sets up lifespan, middleware, routers, exception handlers, and static SPA serving.
"""

import os
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.app.core.config import settings
from backend.app.core.logging import logger, log_event
from backend.app.core.errors import AppError
from backend.app.database import client
from backend.app.api import (
    routes_auth,
    routes_projects,
    routes_publish,
    routes_arcade,
    routes_models,
    routes_health,
    routes_preview,
    ws_studio
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and graceful shutdown lifecycle."""
    logger.info("[STARTUP] Yulya Studio V2 initializing...")
    # Initialize database connection safely
    await client.init_db()
    logger.info("[STARTUP] Yulya Studio V2 running.")
    yield
    logger.info("[SHUTDOWN] Closing database connections and releasing resources...")
    await client.close_db()
    logger.info("[SHUTDOWN] Cleanup complete.")


app = FastAPI(
    title="Yulya Studio V2",
    description="AI-native browser game IDE, persistent voice architect, and visual coding agent",
    version="2.0.0",
    lifespan=lifespan
)

# Exception handler for structured AppErrors
@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError):
    return JSONResponse(
        status_code=exc.status_code,
        content=exc.to_dict()
    )


# CORS Middleware (Section 36)
allowed_origins = [
    settings.BASE_URL,
    "http://localhost:5173",
    "http://localhost:3000",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:10000",
    "http://127.0.0.1:10001",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# Mount Routers
app.include_router(routes_auth.router)
app.include_router(routes_projects.router)
app.include_router(routes_publish.router)
app.include_router(routes_arcade.router)
app.include_router(routes_models.router)
app.include_router(routes_health.router)
app.include_router(ws_studio.router)
app.include_router(routes_preview.router)

# Mount static files
if settings.STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(settings.STATIC_DIR)), name="static")


# Serve Frontend SPA
@app.get("/studio")
@app.get("/{full_path:path}")
async def serve_spa_or_asset(request: Request, full_path: str = ""):
    """Serves the frontend Single Page Application (SPA) for UI routes."""
    # If file exists in frontend/dist, serve it directly
    dist_dir = settings.FRONTEND_DIST_DIR
    target_file = dist_dir / full_path if full_path else dist_dir / "index.html"

    if full_path and target_file.exists() and target_file.is_file():
        return FileResponse(target_file)

    # Fallback to SPA index.html
    index_file = dist_dir / "index.html"
    if index_file.exists():
        return FileResponse(index_file)

    # Fallback template if frontend has not been compiled yet
    return JSONResponse({
        "service": "Yulya Studio V2",
        "status": "ready",
        "message": "Backend API operational. Access /api/health or run Vite frontend."
    })
