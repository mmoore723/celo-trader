"""
api/middleware/auth.py — FastAPI auth dependency.

Validates the session cookie on protected routes and sets the request-scoped
ContextVar so downstream code (config.get_settings, config.get_db_path, broker,
etc.) automatically resolves to the authenticated user's data without any extra
function-signature changes.
"""
from __future__ import annotations
import os
import logging

from fastapi import Request, HTTPException
from jose import jwt, JWTError

logger = logging.getLogger(__name__)

JWT_ALGORITHM = "HS256"
COOKIE_NAME   = "celo_session"


async def require_auth(request: Request) -> None:
    """
    FastAPI dependency injected via  dependencies=[Depends(require_auth)]
    on every protected router.  Sets auth.context ContextVars so all
    downstream helpers (config, db, broker) resolve to the correct user.
    """
    # Lazy-read secret so load_dotenv() has run before we access it.
    secret = os.getenv("JWT_SECRET", "celo-trader-change-me-in-prod")
    token  = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(
            status_code=401,
            detail="Not authenticated",
            headers={"X-Auth-Code": "no_session"},
        )
    try:
        payload = jwt.decode(token, secret, algorithms=[JWT_ALGORITHM])
    except JWTError:
        raise HTTPException(
            status_code=401,
            detail="Session expired — please sign in again",
            headers={"X-Auth-Code": "expired"},
        )

    # Inject user into request-scoped ContextVar
    from auth.context import set_current_user
    set_current_user(
        user_id  = payload.get("sub", "admin"),
        username = payload.get("username", "admin"),
        is_admin = bool(payload.get("is_admin", False)),
    )

    # Also stash on request.state for routes that need to inspect it directly
    request.state.user_id   = payload.get("sub", "admin")
    request.state.username  = payload.get("username", "admin")
    request.state.is_admin  = bool(payload.get("is_admin", False))


# Backward-compat stub — no longer registered but kept for imports
class AuthMiddleware:
    async def dispatch(self, request: Request, call_next):
        return await call_next(request)
