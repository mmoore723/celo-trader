"""
api/middleware/auth.py — Session authentication middleware.

Protects all /api/* routes EXCEPT /api/auth/* routes (login/logout/me).
Reads the HttpOnly 'celo_session' cookie and validates the JWT.
Returns 401 JSON if missing or expired so the React frontend can redirect to /login.
"""
from __future__ import annotations
import os
import logging

from starlette.middleware.base import BaseHTTPMiddleware
from fastapi import Request
from fastapi.responses import JSONResponse
from jose import jwt, JWTError

logger = logging.getLogger(__name__)

JWT_SECRET    = os.getenv("JWT_SECRET", "celo-trader-change-me-in-prod")
JWT_ALGORITHM = "HS256"
COOKIE_NAME   = "celo_session"


# ── FastAPI dependency (replaces BaseHTTPMiddleware) ──────────────────────────
# BaseHTTPMiddleware has a known Starlette bug where cookie parsing can differ
# from route-handler cookie parsing in certain proxy/ASGI configurations.
# Using a dependency instead guarantees the same Request path as route handlers.

async def require_auth(request: Request) -> None:
    """
    FastAPI dependency: validates the session cookie on every protected route.
    Add via  dependencies=[Depends(require_auth)]  on each router that needs auth.
    """
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(
            status_code=401,
            detail="Not authenticated",
            headers={"X-Auth-Code": "no_session"},
        )
    try:
        jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except JWTError:
        raise HTTPException(
            status_code=401,
            detail="Session expired — please sign in again",
            headers={"X-Auth-Code": "expired"},
        )


# Keep the class for backwards-compat import but it is no longer registered.
class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        return await call_next(request)
