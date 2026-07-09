"""
api/routes/auth.py — Multi-user authentication endpoints.

Endpoints:
  POST /api/auth/login    — username + password → session cookie
  GET  /api/auth/me       — current session info
  POST /api/auth/logout   — clear cookie
  POST /api/auth/register — create account via invite token
"""
from __future__ import annotations
import os
import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Response, Request
from pydantic import BaseModel
from jose import jwt, JWTError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/auth", tags=["auth"])

JWT_ALGORITHM = "HS256"
COOKIE_NAME   = "celo_session"
SESSION_SHORT = timedelta(days=7)
SESSION_LONG  = timedelta(days=30)


def _jwt_secret() -> str:
    return os.getenv("JWT_SECRET", "celo-trader-change-me-in-prod")


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
    duration = SESSION_LONG if stay else SESSION_SHORT
    now      = datetime.now(timezone.utc)
    payload  = {
        "sub":      user["id"],
        "username": user["username"],
        "is_admin": user["is_admin"],
        "iat":      int(now.timestamp()),
        "exp":      int((now + duration).timestamp()),
    }
    token = jwt.encode(payload, _jwt_secret(), algorithm=JWT_ALGORITHM)
    response.set_cookie(
        key=COOKIE_NAME, value=token, httponly=True,
        secure=True, samesite="lax",
        max_age=int(duration.total_seconds()), path="/",
    )
    return {"ok": True, "user_id": user["id"], "username": user["username"],
            "is_admin": user["is_admin"]}


def decode_session(token: str) -> dict:
    return jwt.decode(token, _jwt_secret(), algorithms=[JWT_ALGORITHM])


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/login")
async def auth_login(body: LoginRequest, response: Response):
    from auth.users import authenticate
    user = authenticate(body.username, body.password)
    if not user:
        logger.warning("Failed login for username=%s", body.username)
        raise HTTPException(401, "Incorrect username or password")
    logger.info("Login: username=%s id=%s", user["username"], user["id"])
    return _issue_session(response, user, body.stay_signed_in)


@router.get("/me")
async def auth_me(request: Request):
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(401, "Not authenticated")
    try:
        p = decode_session(token)
        return {"ok": True, "user_id": p["sub"], "username": p.get("username", "admin"),
                "is_admin": bool(p.get("is_admin", False)),
                "email": p.get("username", "admin")}
    except JWTError:
        raise HTTPException(401, "Session expired — please sign in again")


@router.post("/logout")
async def auth_logout(response: Response):
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}


@router.post("/register")
async def auth_register(body: RegisterRequest, response: Response):
    """Self-registration via a one-time invite link sent by the admin."""
    from auth.users import consume_invite, create_user, mark_invite_used
    if not body.token or not consume_invite(body.token):
        raise HTTPException(400, "Invalid or expired invite link")
    if len(body.username.strip()) < 3:
        raise HTTPException(400, "Username must be at least 3 characters")
    if len(body.password) < 6:
        raise HTTPException(400, "Password must be at least 6 characters")
    try:
        user = create_user(body.username, body.password, is_admin=False)
    except ValueError as e:
        raise HTTPException(400, str(e))
    mark_invite_used(body.token, user["id"])
    logger.info("New user registered via invite: %s", user["username"])
    return _issue_session(response, user, stay=True)
