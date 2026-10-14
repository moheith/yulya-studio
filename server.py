"""
Production server runner for Yulya Studio V2.
Launches the authoritative FastAPI application via uvicorn.
"""

import os
import uvicorn
from backend.app.core.config import settings


def main():
    port = int(os.environ.get("PORT", settings.PORT))
    host = os.environ.get("HOST", settings.HOST)
    print(f"[STARTUP] Starting Yulya Studio V2 on {host}:{port}")
    uvicorn.run(
        "backend.app.main:app",
        host=host,
        port=port,
        reload=False,
        log_level="info",
        access_log=True,
    )


if __name__ == "__main__":
    main()
