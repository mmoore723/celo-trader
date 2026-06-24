"""
api/main.py — FastAPI application entry point.

Run with:  uvicorn api.main:app --host 0.0.0.0 --port 8501 --reload
"""
from __future__ import annotations
import sys
from pathlib import Path

# Ensure bot modules (trading_logic, config, broker, etc.) are importable
# when running from the project root.
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

# ── Boot bot modules ──────────────────────────────────────────────────────────
try:
    from logger_config import setup_logging
    setup_logging()
except Exception:
    pass

from database import init_db
init_db()

# ── Create app ────────────────────────────────────────────────────────────────
app = FastAPI(
    title="Celo Trader API",
    description="FastAPI backend for Celo Trader algorithmic options bot",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # tighten in production if needed
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Register API routes ───────────────────────────────────────────────────────
from api.routes import bot, market, trades, settings, ws, backtest

app.include_router(bot.router)
app.include_router(market.router)
app.include_router(trades.router)
app.include_router(settings.router)
app.include_router(ws.router)
app.include_router(backtest.router)

# ── Serve built React frontend ────────────────────────────────────────────────
_DIST = _ROOT / "frontend" / "dist"

if _DIST.exists():
    # Serve static assets (JS, CSS, images)
    app.mount("/assets", StaticFiles(directory=str(_DIST / "assets")), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa(full_path: str) -> FileResponse:
        """Catch-all: serve index.html for all non-API routes (React Router)."""
        index = _DIST / "index.html"
        return FileResponse(str(index))
else:
    @app.get("/", include_in_schema=False)
    async def dev_root() -> dict:
        return {
            "status": "API running",
            "note": "React frontend not built yet. Run: cd frontend && npm run build",
            "docs": "/docs",
        }
