"""
api/routes/auth.py — Multi-user authentication endpoints.

Endpoints:
  POST /api/auth/login    — username + password → session cookie
  GET  /api/auth/me       — current session info
  POST /api/auth/logout   — clear cookie
  POST /api/auth/register — create account via invite token
"""
from __future__ import annotations
import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Response, Request
from pydantic import BaseModel
from jose import jwt, JWTError
from auth.security import JWT_ALGORITHM, COOKIE_NAME, LOGIN_GUARD, jwt_secret

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/auth", tags=["auth"])

SESSION_SHORT = timedelta(days=7)
SESSION_LONG  = timedelta(days=30)


# ── Pydantic models ───────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    username:       str
    password:       str
    stay_signed_in: bool = False


class RegisterRequest(BaseModel):
    token:    str       # invite token
    username: str
    password: str


# ── Helpers ───────────────────────────────────────────────────────────────────

def _issue_session(response: Response, user: dict, stay: bool) -> dict:
    from auth.users import CURRENT_TERMS_VERSION
    duration = SESSION_LONG if stay else SESSION_SHORT
    now      = datetime.now(timezone.utc)
    payload  = {
        "sub":      user["user_id"],
        "username": user["username"],
        "is_admin": user["is_admin"],
        "session_version": int(user["session_version"]),
        "iat":      int(now.timestamp()),
        "exp":      int((now + duration).timestamp()),
    }
    token = jwt.encode(payload, jwt_secret(), algorithm=JWT_ALGORITHM)
    response.set_cookie(
        key=COOKIE_NAME, value=token, httponly=True,
        secure=True, samesite="lax",
        max_age=int(duration.total_seconds()), path="/",
    )
    return {"ok": True, "user_id": user["user_id"], "username": user["username"],
            "is_admin": user["is_admin"],
            "terms_accepted": user.get("terms_version") == CURRENT_TERMS_VERSION}


def decode_session(token: str) -> dict:
    return jwt.decode(token, jwt_secret(), algorithms=[JWT_ALGORITHM])


def _current_session_user(token: str) -> tuple[dict, dict]:
    payload = decode_session(token)
    from auth.users import get_user
    user = get_user(str(payload.get("sub") or ""))
    if not user or int(payload.get("session_version", 0)) != int(user["session_version"]):
        raise JWTError("revoked session")
    return payload, user


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/login")
async def auth_login(body: LoginRequest, response: Response, request: Request):
    from auth.users import authenticate
    client = request.client.host if request.client else "unknown"
    key = f"{client}:{body.username.strip().lower()}"
    if LOGIN_GUARD.blocked(key):
        raise HTTPException(429, "Too many failed attempts. Try again later.")
    user = authenticate(body.username, body.password)
    if not user:
        LOGIN_GUARD.failure(key)
        logger.warning("Failed login for username=%s", body.username)
        raise HTTPException(401, "Incorrect username or password")
    LOGIN_GUARD.success(key)
    logger.info("Login: username=%s id=%s", user["username"], user["user_id"])
    return _issue_session(response, user, body.stay_signed_in)


@router.get("/me")
async def auth_me(request: Request):
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(401, "Not authenticated")
    try:
        p, u = _current_session_user(token)
        from auth.users import get_user, CURRENT_TERMS_VERSION
        # JWT layer: terms_version baked in when user accepted (re-issued cookie).
        # DB layer: fallback for sessions issued before this feature was added.
        # Either source matching CURRENT_TERMS_VERSION = user has accepted.
        jwt_terms = p.get("terms_version")
        db_terms  = u.get("terms_version")
        accepted_v = jwt_terms if jwt_terms == CURRENT_TERMS_VERSION else db_terms
        return {
            "ok":                    True,
            "user_id":               u["user_id"],
            "username":              u["username"],
            "is_admin":              bool(u["is_admin"]),
            "email":                 u["username"],
            "terms_accepted":        accepted_v == CURRENT_TERMS_VERSION,
            "current_terms_version": CURRENT_TERMS_VERSION,
        }
    except JWTError:
        raise HTTPException(401, "Session expired — please sign in again")


@router.post("/accept-terms")
async def auth_accept_terms(request: Request, response: Response):
    """
    Record that the authenticated user accepted the current ToS.

    Two-layer persistence:
      1. DB write (terms_version column in users table) — survives restarts.
      2. Re-issued session cookie with terms_version baked into the JWT —
         protects against DB resets or failed writes so the user never gets
         re-prompted mid-session, and the /me endpoint can trust the JWT alone.
    """
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(401, "Not authenticated")
    try:
        p, u = _current_session_user(token)
    except JWTError:
        raise HTTPException(401, "Session expired — please sign in again")
    from auth.users import accept_terms, CURRENT_TERMS_VERSION
    # Write to DB (primary storage)
    ok = accept_terms(u["user_id"], CURRENT_TERMS_VERSION)
    if not ok:
        raise HTTPException(401, "User account no longer exists")
    # Re-issue the cookie with terms_version embedded so /me can trust the JWT
    # even if the DB row is later missing.  Preserve the original expiry.
    _now_ts  = int(datetime.now(timezone.utc).timestamp())
    _exp     = p.get("exp", _now_ts + int(SESSION_SHORT.total_seconds()))
    _max_age = max(0, _exp - _now_ts)
    new_payload = {
        **p,
        "username": u["username"],
        "is_admin": bool(u["is_admin"]),
        "session_version": int(u["session_version"]),
        "terms_version": CURRENT_TERMS_VERSION,
    }
    new_token   = jwt.encode(new_payload, jwt_secret(), algorithm=JWT_ALGORITHM)
    response.set_cookie(
        key=COOKIE_NAME, value=new_token, httponly=True,
        secure=True, samesite="lax", max_age=_max_age, path="/",
    )
    return {"ok": True, "terms_version": CURRENT_TERMS_VERSION}


@router.post("/logout")
async def auth_logout(response: Response):
    response.delete_cookie(
        COOKIE_NAME, path="/", secure=True, httponly=True, samesite="lax"
    )
    return {"ok": True}


@router.post("/register")
async def auth_register(body: RegisterRequest, response: Response):
    """Self-registration via a one-time invite link sent by the admin."""
    from auth.users import create_user_from_invite
    try:
        user = create_user_from_invite(body.token, body.username, body.password)
    except ValueError as e:
        raise HTTPException(400, str(e))
    logger.info("New user registered via invite: %s", user["username"])
    return _issue_session(response, user, stay=True)
