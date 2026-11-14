"""
api/middleware/auth.py — FastAPI auth dependency.

Validates the session cookie on protected routes and sets the request-scoped
ContextVar so downstream code (config.get_settings, config.get_db_path, broker,
etc.) automatically resolves to the authenticated user's data without any extra
function-signature changes.
"""
from __future__ import annotations
import logging

from fastapi import Request, HTTPException
from jose import jwt, JWTError
from auth.security import (
    JWT_ALGORITHM, COOKIE_NAME, jwt_secret, origin_is_trusted,
)

logger = logging.getLogger(__name__)

async def require_auth(request: Request) -> None:
    """
    FastAPI dependency injected via  dependencies=[Depends(require_auth)]
    on every protected router.  Sets auth.context ContextVars so all
    downstream helpers (config, db, broker) resolve to the correct user.
    """
    # Lazy-read secret so load_dotenv() has run before we access it.
    token  = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(
            status_code=401,
            detail="Not authenticated",
            headers={"X-Auth-Code": "no_session"},
        )
    try:
        payload = jwt.decode(token, jwt_secret(), algorithms=[JWT_ALGORITHM])
    except JWTError:
        raise HTTPException(
            status_code=401,
            detail="Session expired — please sign in again",
            headers={"X-Auth-Code": "expired"},
        )

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid session")
    from auth.users import get_user
    user = get_user(str(user_id))
    if not user or int(payload.get("session_version", 0)) != int(user["session_version"]):
        raise HTTPException(
            status_code=401,
            detail="Session is no longer valid — please sign in again",
            headers={"X-Auth-Code": "revoked"},
        )

    # Cookie-authenticated state changes must originate from our own UI.
    if request.method.upper() not in {"GET", "HEAD", "OPTIONS"}:
        source = request.headers.get("origin") or request.headers.get("referer")
        if source and not origin_is_trusted(source):
            raise HTTPException(status_code=403, detail="Untrusted request origin")

    from auth.customer_access import enforce_customer_access
    enforce_customer_access(user, request.method, request.url.path)

    # Inject current DB truth, not role/name claims cached in the JWT.
    from auth.context import set_current_user
    set_current_user(
        user_id=user["user_id"],
        username=user["username"],
        is_admin=bool(user["is_admin"]),
    )

    # Also stash on request.state for routes that need to inspect it directly
    request.state.user_id = user["user_id"]
    request.state.username = user["username"]
    request.state.is_admin = bool(user["is_admin"])


# Backward-compat stub — no longer registered but kept for imports
class AuthMiddleware:
    async def dispatch(self, request: Request, call_next):
        return await call_next(request)
