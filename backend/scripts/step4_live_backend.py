"""Run Backend for STEP 4 live mirror against local Worker. bootstrap_schema, isolated DB."""

from __future__ import annotations

import uvicorn

from app.core.config import Settings
from app.main import create_app

settings = Settings(
    database_url="sqlite+aiosqlite:///../data/step4_live_mirror.db",
    execution_worker_url="http://127.0.0.1:8001",
    cors_origins="http://127.0.0.1:5173,http://localhost:5173",
    execution_mode="hyperliquid",
)
app = create_app(settings=settings, bootstrap_schema=True)

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")
