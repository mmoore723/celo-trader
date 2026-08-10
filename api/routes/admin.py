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


class ResetPasswordRequest(BaseModel):
    new_password: str


class MaintenanceRequest(BaseModel):
    message: str = ""   # shown on maintenance screen, e.g. "Back online at 3 PM ET"
    collection_only: bool = False


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
    # Password complexity enforced inside create_user() via validate_password()
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


@router.post("/users/{user_id}/reset-password")
async def reset_user_password(user_id: str, request: Request, body: ResetPasswordRequest):
    """Admin resets any user's password."""
    _require_admin(request)
    # Complexity enforced inside reset_password() via validate_password()
    from auth.users import reset_password as _reset
    try:
        ok = _reset(user_id, body.new_password)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not ok:
        raise HTTPException(404, "User not found")
    logger.info("Admin %s reset password for user_id=%s", request.state.username, user_id)
    return {"ok": True}


# ── Maintenance mode ──────────────────────────────────────────────────────────

@router.get("/maintenance/status")
async def get_maintenance_status(request: Request):
    """Return current maintenance mode state (admin only)."""
    _require_admin(request)
    from config import get_maintenance_state
    s = get_maintenance_state()
    return {
        "active":  bool(s.get("maintenance_mode", False)),
        "message": str(s.get("maintenance_message", "")),
        "collection_only": bool(s.get("collection_only", False)),
    }


@router.post("/maintenance/enable")
async def enable_maintenance(request: Request, body: MaintenanceRequest):
    """
    Emergency maintenance mode:
      1. Stops every bot loop immediately, unless research collection is
         explicitly requested.
      2. Writes a system-wide maintenance_mode=True + message so:
         - /api/bot/start is blocked for all users.
         - Non-admin users see the maintenance screen.

    It deliberately does not submit liquidation orders for other users. A
    cross-account close must be an explicit, separately confirmed operation.
    """
    _require_admin(request)
    from trading.loop import stop_loop
    from config import save_maintenance_state
    from auth.users import list_users

    # Lock starts and auto-resumes before signalling any loop. This is the
    # durable safety guarantee even if a single loop is asleep or unhealthy.
    save_maintenance_state(True, body.message, collection_only=body.collection_only)
    stopped: list[str] = []
    warnings: list[str] = []
    if not body.collection_only:
        for user in list_users():
            user_id = str(user["user_id"])
            try:
                stop_loop(user_id)
                stopped.append(user_id)
            except Exception as e:
                warnings.append(f"{user_id}: {e}")

    logger.info(
        "🔧 MAINTENANCE MODE ENABLED by %s — message: %s",
        request.state.username, body.message.strip() or "(none)"
    )
    return {
        "ok": True,
        "message": (
            "Maintenance active. Existing loops are collecting research data only; "
            "no orders or exits can be sent."
            if body.collection_only else
            "Maintenance active. All bot loops halted; positions were left untouched."
        ),
        "halted_users": stopped,
        "warnings": warnings,
        "collection_only": bool(body.collection_only),
    }


@router.post("/maintenance/disable")
async def disable_maintenance(request: Request):
    """
    Clear maintenance mode. Bot can be started normally after this.
    Does NOT automatically restart the bot — admin must press Start Bot.
    """
    _require_admin(request)
    from config import save_maintenance_state

    save_maintenance_state(False)

    logger.info("✅ MAINTENANCE MODE CLEARED by %s", request.state.username)
    return {"ok": True, "message": "Maintenance mode cleared. You can now restart the bot."}


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
