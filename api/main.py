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

from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from api.middleware.auth import require_auth

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
    allow_origins=["https://celotrader.com", "http://celotrader.com",
                   "http://localhost:5173", "http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,  # required for session cookies
)

# ── Register API routes ───────────────────────────────────────────────────────
# Auth is enforced via Depends(require_auth) on each protected router.
# /api/auth/* routes have no dependency — they are always public.
from api.routes import bot, market, trades, settings, ws, backtest
import api.routes.auth as auth_routes

_auth = [Depends(require_auth)]

app.include_router(auth_routes.router)                              # public
app.include_router(bot.router,      dependencies=_auth)
app.include_router(market.router,   dependencies=_auth)
app.include_router(trades.router,   dependencies=_auth)
app.include_router(settings.router, dependencies=_auth)
app.include_router(ws.router)                                       # WebSocket — no cookie auth
app.include_router(backtest.router, dependencies=_auth)

# ── Serve built React frontend ────────────────────────────────────────────────
_DIST = _ROOT / "frontend" / "dist"

if _DIST.exists():
    # Serve static assets (JS, CSS, images)
    app.mount("/assets", StaticFiles(directory=str(_DIST / "assets")), name="assets")

    # ── Explicit static file routes BEFORE the catch-all ─────────────────────
    # The catch-all /{full_path:path} would otherwise intercept any file
    # requests (favicon.svg, logo.png, robots.txt, etc.) and return index.html.
    # List every static file in dist/ root that the browser might request.
    _STATIC_ROOT_FILES = ["favicon.svg", "favicon.ico", "favicon.png",
                          "logo.png", "logo.svg", "mascot.png",
                          "robots.txt", "site.webmanifest"]
    for _fname in _STATIC_ROOT_FILES:
        _fpath = _DIST / _fname
        if _fpath.exists():
            # Use a closure to capture _fpath correctly inside the loop
            def _make_handler(p: Path):
                async def _handler():
                    return FileResponse(str(p))
                return _handler
            app.get(f"/{_fname}", include_in_schema=False)(_make_handler(_fpath))

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa(full_path: str) -> FileResponse:
        """Catch-all: serve index.html for all non-API routes (React Router).
        Cache-Control: no-cache forces browsers to always revalidate index.html.
        JS/CSS assets have content-hashed filenames so they stay cached correctly.
        Without this, a browser caches the old index.html and keeps loading the
        old JS bundle even after a deploy — causing auth failures and blank charts.
        """
        index = _DIST / "index.html"
        return FileResponse(str(index), headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        })
else:
    @app.get("/", include_in_schema=False)
    async def dev_root() -> dict:
        return {
            "status": "API running",
            "note": "React frontend not built yet. Run: cd frontend && npm run build",
            "docs": "/docs",
        }
