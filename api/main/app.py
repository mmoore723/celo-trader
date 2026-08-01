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
from api.main.lifespan import _lifespan

# ── Create app ────────────────────────────────────────────────────────────────
app = FastAPI(
    lifespan=_lifespan,
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
from api.routes import bot, market, trades, settings, ws, backtest, admin, strategy_health, ai_reasoning, signals, tickers
import api.routes.auth as auth_routes

_auth = [Depends(require_auth)]

app.include_router(auth_routes.router)                              # public
app.include_router(bot.router,      dependencies=_auth)
app.include_router(market.router,   dependencies=_auth)
app.include_router(trades.router,   dependencies=_auth)
app.include_router(settings.router, dependencies=_auth)
app.include_router(admin.router,    dependencies=_auth)             # admin — auth required
app.include_router(ws.router)                                       # WebSocket — no cookie auth
app.include_router(backtest.router,        dependencies=_auth)
app.include_router(strategy_health.router, dependencies=_auth)
app.include_router(ai_reasoning.router,    dependencies=_auth)
app.include_router(signals.router,         dependencies=_auth)
app.include_router(tickers.router,         dependencies=_auth)
