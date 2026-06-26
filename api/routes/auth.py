"""
api/routes/auth.py — Password-based authentication routes.

Simple single-user login: one hashed password stored in .env.
Issues a signed JWT session cookie on success.

Endpoints:
  POST /api/auth/login   — verify password → issue session cookie
  GET  /api/auth/me      — check current session
  POST /api/auth/logout  — clear session cookie

Dependencies:
  pip install python-jose[cryptography] passlib[bcrypt]

Setup:
  1. Generate a hashed password:
       python3 -c "from passlib.hash import bcrypt; print(bcrypt.hash('yourpassword'))"
  2. Add to .env:
       DASHBOARD_PASSWORD_HASH=$2b$12$...the hash...
       JWT_SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))")
"""
from __future__ import annotations
import os
import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Request, HTTPException, Response
from pydantic import BaseModel
from jose import jwt, JWTError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/auth", tags=["auth"])

# ── Config ─────────────────────────────────────────────────────────────────────
JWT_SECRET    = os.getenv("JWT_SECRET", "celo-trader-change-me-in-prod")
JWT_ALGORITHM = "HS256"
COOKIE_NAME   = "celo_session"

# bcrypt hash of the dashboard password (set in .env)
PASSWORD_HASH = os.getenv("DASHBOARD_PASSWORD_HASH", "")

# Fallback plaintext password for first-time setup only (not recommended for prod)
DASHBOARD_PASSWORD = os.getenv("DASHBOARD_PASSWORD", "")

SESSION_SHORT = timedelta(hours=24)   # without "stay signed in"
SESSION_LONG  = timedelta(days=30)    # with "stay signed in"


# ── Request body ───────────────────────────────────────────────────────────────
class LoginRequest(BaseModel):
    password: str
    stay_signed_in: bool = False


# ── Helpers ────────────────────────────────────────────────────────────────────
def _verify_password(plain: str) -> bool:
    """Check the submitted password against the stored hash (or plaintext fallback)."""
    if PASSWORD_HASH:
        try:
            from passlib.hash import bcrypt
            return bcrypt.verify(plain, PASSWORD_HASH)
        except Exception as e:
            logger.error("bcrypt verify error: %s", e)
            return False
    # Plaintext fallback — only useful for initial local dev setup
    if DASHBOARD_PASSWORD:
        return plain == DASHBOARD_PASSWORD
    logger.error("No DASHBOARD_PASSWORD_HASH or DASHBOARD_PASSWORD set in .env")
    return False


def _issue_session(response: Response, stay: bool) -> dict:
    """Sign a JWT and attach it as a secure HttpOnly cookie."""
    duration = SESSION_LONG if stay else SESSION_SHORT
    now = datetime.now(timezone.utc)
    payload = {
        "sub":  "admin",
        "iat":  int(now.timestamp()),
        "exp":  int((now + duration).timestamp()),
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,          # JS cannot read the cookie
        secure=True,            # HTTPS only (set secure=False for local http dev)
        samesite="lax",
        max_age=int(duration.total_seconds()),
        path="/",
    )
    return {"ok": True}


def _decode_session(token: str) -> dict:
    return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])


# ── Routes ─────────────────────────────────────────────────────────────────────
@router.post("/login")
async def auth_login(body: LoginRequest, response: Response):
    """Verify dashboard password and issue a session cookie."""
    if not _verify_password(body.password):
        logger.warning("Failed login attempt")
        raise HTTPException(401, "Incorrect password")
    logger.info("Dashboard login successful (stay=%s)", body.stay_signed_in)
    return _issue_session(response, body.stay_signed_in)


@router.get("/me")
async def auth_me(request: Request):
    """
    Returns 200 if a valid session cookie is present, 401 otherwise.
    Called by the frontend on page load to check auth state.
    """
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(401, "Not authenticated")
    try:
        _decode_session(token)
        return {"ok": True}
    except JWTError:
        raise HTTPException(401, "Session expired — please sign in again")


@router.post("/logout")
async def auth_logout(response: Response):
    """Clear the session cookie."""
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}
