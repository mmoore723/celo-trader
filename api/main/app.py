"""
api/main/app.py — creates the FastAPI app instance, adds CORS middleware,
and registers every API router.

Split out of the old single api/main.py (2026-08-01, file-size cleanup);
no logic changed, only relocated. Imported by api/main/__init__.py AFTER
api.main.bootstrap has already run (sys.path set, logger configured, DB
initialized) — this file and every api.routes.* module it imports
transitively depends on root-level bare modules being importable.
"""
from __future__ import annotations

from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware

from api.middleware.auth import require_auth
from api.middleware.research_access import require_research_admin, require_internal_review
from api.main.lifespan import _lifespan
from auth.security import (
    allowed_browser_origins, is_production, validate_security_configuration,
)

validate_security_configuration()

# ── Create app ────────────────────────────────────────────────────────────────
app = FastAPI(
    lifespan=_lifespan,
    title="Celo Trader API",
    description="FastAPI backend for Celo Trader algorithmic options bot",
    version="2.0.0",
    docs_url=None if is_production() else "/docs",
    redoc_url=None if is_production() else "/redoc",
    openapi_url=None if is_production() else "/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_browser_origins(),
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,  # required for session cookies
)


@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), geolocation=(), microphone=()"
    if is_production():
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


@app.get("/healthz", include_in_schema=False)
async def healthz() -> dict:
    return {"ok": True, "service": "celo-trader"}

# ── Register API routes ───────────────────────────────────────────────────────
# Auth is enforced via Depends(require_auth) on each protected router.
# /api/auth/* routes have no dependency — they are always public.
from api.routes import bot, market, trades, settings, ws, backtest, admin, strategy_health, ai_reasoning, learning, signals, tickers, option_chart
import api.routes.auth as auth_routes

_auth = [Depends(require_auth)]
_research = [Depends(require_research_admin)]

from api.routes import launch
app.include_router(launch.router)
app.include_router(auth_routes.router)                              # public
app.include_router(bot.router,      dependencies=_auth)
app.include_router(market.router,   dependencies=_auth)
app.include_router(trades.router,   dependencies=_auth)
app.include_router(option_chart.router, dependencies=_auth)
app.include_router(settings.router, dependencies=_auth)
app.include_router(admin.router,    dependencies=_auth)             # admin — auth required
app.include_router(ws.router)                                       # WebSocket — no cookie auth
app.include_router(backtest.router,        dependencies=_research)
app.include_router(strategy_health.router, dependencies=[Depends(require_internal_review)])
from api.routes import weekly_exit_audit
app.include_router(weekly_exit_audit.router, dependencies=_research)
from api.routes import exit_lab
app.include_router(exit_lab.router, dependencies=_research)
from api.routes import session_capture
app.include_router(session_capture.router, dependencies=_research)
app.include_router(ai_reasoning.router,    dependencies=_auth)
app.include_router(learning.router,        dependencies=_auth)
app.include_router(signals.router,         dependencies=_auth)
app.include_router(tickers.router,         dependencies=_auth)
