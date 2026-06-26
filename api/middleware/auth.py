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

# Path prefixes that skip authentication entirely
_PUBLIC_PREFIXES = (
    "/api/auth/",   # login / logout / me
    "/api/auth",    # handles exact /api/auth without trailing slash
)


class AuthMiddleware(BaseHTTPMiddleware):
    """
    Starlette middleware that rejects unauthenticated requests to /api/* endpoints.

    Non-API paths (the React SPA) pass through without any check — the frontend
    uses its own AuthContext to decide whether to show Login.tsx or AppShell.
    """

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Non-API traffic (React SPA, static files) → always pass through
        if not path.startswith("/api/"):
            return await call_next(request)

        # Auth endpoints are always public
        if path.startswith(_PUBLIC_PREFIXES):
            return await call_next(request)

        # All other /api/* endpoints require a valid session cookie
        token = request.cookies.get(COOKIE_NAME)
        if not token:
            return JSONResponse(
                {"detail": "Not authenticated", "code": "no_session"},
                status_code=401,
            )

        try:
            jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        except JWTError:
            return JSONResponse(
                {"detail": "Session expired — please sign in again", "code": "expired"},
                status_code=401,
            )

        return await call_next(request)
