"""
api/routes/admin.py — Admin-only user management endpoints.

All routes require a valid session AND is_admin=True.
The frontend's /admin page calls these to create/invite/delete users.
"""
from __future__ import annotations
import logging
import os

from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin", tags=["admin"])


def _require_admin(request: Request) -> None:
    """Raise 403 if the caller is not an admin."""
    if not getattr(request.state, "is_admin", False):
        raise HTTPException(403, "Admin access required")


# ── Models ────────────────────────────────────────────────────────────────────

class CreateUserRequest(BaseModel):
    username: str
    password: str
    is_admin: bool = False


class InviteRequest(BaseModel):
    hours: int = 48   # link validity window


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/users")
async def list_users(request: Request):
    _require_admin(request)
    from auth.users import list_users as _list
    return {"users": _list()}


@router.post("/users")
async def create_user(request: Request, body: CreateUserRequest):
    """Admin creates an account directly (no invite needed)."""
    _require_admin(request)
    if len(body.username.strip()) < 3:
        raise HTTPException(400, "Username must be at least 3 characters")
    if len(body.password) < 6:
        raise HTTPException(400, "Password must be at least 6 characters")
    from auth.users import create_user as _create
    try:
        user = _create(body.username, body.password, is_admin=body.is_admin)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True, "user": user}


@router.delete("/users/{user_id}")
async def delete_user(user_id: str, request: Request):
    _require_admin(request)
    from auth.users import delete_user as _delete
    try:
        ok = _delete(user_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not ok:
        raise HTTPException(404, "User not found")
    return {"ok": True}


@router.post("/invite")
async def create_invite(request: Request, body: InviteRequest):
    """Generate a single-use invite link valid for `hours` hours."""
    _require_admin(request)
    from auth.users import create_invite as _invite
    token    = _invite(created_by=request.state.user_id, hours=body.hours)
    # Build the link using the request's host (works on both local + EC2)
    base_url = str(request.base_url).rstrip("/")
    link     = f"{base_url}/#/register?token={token}"
    logger.info("Invite link created by %s: %s", request.state.username, link)
    return {"ok": True, "token": token, "link": link, "expires_hours": body.hours}
