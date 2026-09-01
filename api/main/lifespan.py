"""
api/main/lifespan.py — service-restart auto-resume + FastAPI lifespan hook.

Split out of the old single api/main.py (2026-08-01, file-size cleanup);
no logic changed, only relocated.
"""
from __future__ import annotations

import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI

_learning_stop = threading.Event()


def _learning_curation_worker() -> None:
    """Refresh each tenant's real-example manifest hourly, outside request paths."""
    import logging
    from auth.context import set_current_user
    while not _learning_stop.is_set():
        try:
            from auth.users import list_users
            from api.routes.learning import _sync_curated_examples
            for user in list_users():
                try:
                    set_current_user(user["user_id"], user["username"], bool(user["is_admin"]))
                    _sync_curated_examples()
                except Exception as exc:
                    logging.getLogger("celo_trader.learning").warning(
                        "learning curation failed for user %s (non-fatal): %s", user["user_id"], exc,
                    )
        except Exception as exc:
            logging.getLogger("celo_trader.learning").warning("learning curation failed (non-fatal): %s", exc)
        finally:
            set_current_user("system", "system", False)
        _learning_stop.wait(3600)


def _auto_start_bot_if_needed() -> None:
    """
    If the service was restarted (crash, deploy, systemd restart) and the bot
    was running before, auto-start it in a background thread so the user doesn't
    have to manually press Start Bot every time.

    For each known user, reads that user's own bot_state.json: if "running"
    == True and "auto_start_disabled" != True, spawns their trading loop as a
    daemon thread. Any exception is logged and swallowed so a broken
    environment never prevents the API from booting.

    FIX: this used to check ONLY the single legacy root-level bot_state.json
    and always resume as the "admin" user — on a service restart, any other
    user's bot that was running before the restart silently stayed stopped,
    with nothing telling them it hadn't resumed. Now iterates every
    registered user (auth.users.list_users) and resumes each one whose own
    state file says it was running.
    """
    try:
        from config import (
            atomic_update_json,
            get_api_keys,
            get_bot_state_path,
            load_bot_state_safely,
            get_maintenance_state,
        )
        from auth.users import list_users
        from trading.loop import run_trading_loop

        try:
            user_ids = [u["user_id"] for u in list_users()]
        except Exception:
            # users table may not exist yet on a very first boot — fall back
            # to just admin so a fresh install still auto-resumes correctly.
            user_ids = ["admin"]

        maintenance = get_maintenance_state()
        if maintenance.get("maintenance_mode", False) and not maintenance.get("collection_only", False):
            return

        for uid in user_ids:
            try:
                _state_file = get_bot_state_path(uid)
                if not _state_file.exists():
                    continue
                state = load_bot_state_safely(_state_file)
                if state is None:
                    continue
                if not state.get("running", False):
                    continue
                if state.get("auto_start_disabled", False):
                    continue
                credentials = get_api_keys(uid)
                from config import get_settings
                from broker import required_broker_credentials
                user_settings = get_settings(uid)
                if not all(
                    str(credentials.get(key) or "").strip()
                    for key, _label in required_broker_credentials(
                        credentials,
                        provider=str(user_settings.get("broker_provider") or "alpaca"),
                        paper=bool(user_settings.get("paper_trading", True)),
                    )
                ):
                    # A stale RUNNING flag must not create a fake $5,000
                    # account or repeatedly probe broker APIs with empty keys.
                    atomic_update_json(
                        _state_file,
                        lambda saved: {
                            **saved,
                            "running": False,
                            "mode": "stopped",
                            "account_balance": 0.0,
                            "day_start_balance": 0.0,
                            "options_buying_power": 0.0,
                            "network_ok": False,
                        },
                    )
                    continue
                # Bot was running before the restart — resume it
                t = threading.Thread(
                    target=run_trading_loop,
                    kwargs={"user_id": uid},
                    daemon=True,
                    name=f"celo-bot-{uid}",
                )
                t.start()
                # Log to DB so the THINKING panel shows the auto-resume event
                try:
                    from database import log_event
                    log_event("INFO", "trading_logic",
                              f"🔄 Service restarted — bot auto-resumed for user {uid}.")
                except Exception:
                    pass
            except Exception as _ue:
                import logging
                logging.getLogger("celo_trader").warning(
                    "auto_start_bot_if_needed failed for user %s (non-fatal): %s", uid, _ue
                )
    except Exception as _e:
        import logging
        logging.getLogger("celo_trader").warning(
            "auto_start_bot_if_needed failed (non-fatal): %s", _e
        )


@asynccontextmanager
async def _lifespan(app: FastAPI):
    """Auto-resume on boot and coordinate loop shutdown on service exit."""
    _auto_start_bot_if_needed()
    _learning_stop.clear()
    threading.Thread(target=_learning_curation_worker, daemon=True, name="learning-curator").start()
    try:
        yield
    finally:
        import logging
        from trading.state import request_graceful_shutdown
        _learning_stop.set()

        still_running = request_graceful_shutdown(timeout=15.0)
        if still_running:
            logging.getLogger("celo_trader").warning(
                "Trading loops did not finish before shutdown deadline: %s",
                ", ".join(still_running),
            )
