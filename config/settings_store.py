"""
config/settings_store.py — Per-user settings persistence (get/save) and
per-user API key management (get/save), plus the setup_logging() shim.

Split out of the old single config.py (2026-08-01, file-size cleanup); no
logic changed, only relocated.
"""

import json
import logging

from config.paths import (
    get_user_data_dir, _get_user_id, SETTINGS_PATH, BASE_DIR,
    SYSTEM_MAINTENANCE_PATH,
)
from config.defaults import _DEFAULTS
from config.env_keys import ALPACA_API_KEY, ALPACA_SECRET_KEY, TRADIER_API_KEY, TRADIER_ACCOUNT_ID
from config.logging_settings import LOG_LEVEL, LOG_FORMAT


_RETIRED_STRATEGY_SETTING_KEYS = frozenset({
    "strategy_orb_enabled", "strategy_bos_enabled", "strategy_vwap_enabled",
    "strategy_fvg_enabled", "strategy_ifvg_enabled", "strategy_chan_enabled",
    "strategy_mid_enabled", "strategy_tcont_enabled", "strategy_aft_enabled",
    "strategy_gapgo_enabled", "strategy_liqsweep_enabled",
    "strategy_trend_cont_v2_enabled", "strategy_spy_afternoon_reversal_v2_enabled",
    "strategy_tsla_noise_momentum_v2_enabled",
})


def get_settings(user_id: str | None = None) -> dict:
    """
    Return settings for the given (or current) user, falling back through:
      1. user_data/{user_id}/settings.json  (per-user override)
      2. user_settings.json                 (legacy single-user file)
      3. _DEFAULTS                          (hardcoded defaults)
    """
    settings = _DEFAULTS.copy()
    uid      = user_id or _get_user_id()

    # Load per-user settings if the file exists
    _user_settings = get_user_data_dir(uid) / "settings.json"
    _paths = [_user_settings, SETTINGS_PATH]   # user-specific first, then legacy
    for _p in _paths:
        if _p.exists():
            try:
                with open(_p, "r") as f:
                    overrides = json.load(f)
                settings.update(overrides)
                break   # first hit wins
            except (json.JSONDecodeError, OSError):
                pass
    # Reviewed promotion is owned by code, not by a browser payload.  Use the
    # catalog as the exact source of truth so a strategy which has not met its
    # sample/holdout requirement cannot remain runnable through an old saved
    # settings file.
    try:
        from config.strategy_catalog import REVIEWED_STRATEGIES, reviewed_strategy_ids
        settings["validated_strategy_ids"] = sorted(reviewed_strategy_ids())
        approved_setting_keys = {rule.setting_key for rule in REVIEWED_STRATEGIES.values()}
        for key in _RETIRED_STRATEGY_SETTING_KEYS - approved_setting_keys:
            settings[key] = False
    except Exception:
        # Settings must remain available during an incomplete deploy.
        pass
    return settings


def save_settings(updates: dict, user_id: str | None = None) -> None:
    uid     = user_id or _get_user_id()
    _path   = get_user_data_dir(uid) / "settings.json"
    current = get_settings(user_id=uid)
    current.update(updates)
    with open(_path, "w") as f:
        json.dump(current, f, indent=2)


def get_maintenance_state() -> dict:
    """Return the global maintenance state, never a per-user preference."""
    default = {
        "maintenance_mode": False,
        "maintenance_message": "",
        # When maintenance is active, this keeps already-running paper loops
        # alive only to record research evidence.  It never authorizes orders.
        "collection_only": False,
    }
    try:
        payload = json.loads(SYSTEM_MAINTENANCE_PATH.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return default
        return {
            "maintenance_mode": bool(payload.get("maintenance_mode", False)),
            "maintenance_message": str(payload.get("maintenance_message", "")),
            "collection_only": bool(payload.get("collection_only", False)),
        }
    except (OSError, json.JSONDecodeError):
        return default


def save_maintenance_state(
    active: bool, message: str = "", *, collection_only: bool = False
) -> None:
    """Atomically save the system-wide trading-halt state.

    ``collection_only`` is meaningful only while the halt is active.  It lets
    existing paper loops scan and write research records, but execution code
    treats the halt as an absolute no-order/no-exit boundary.
    """
    SYSTEM_MAINTENANCE_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "maintenance_mode": bool(active),
        "maintenance_message": message.strip() if active else "",
        "collection_only": bool(active and collection_only),
    }
    temporary = SYSTEM_MAINTENANCE_PATH.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    temporary.replace(SYSTEM_MAINTENANCE_PATH)


# ── Per-user API key management ───────────────────────────────────────────────

def get_api_keys(user_id: str | None = None) -> dict:
    """
    Return decrypted API keys for the user.  Priority:
      1. user_data/{user_id}/credentials.enc  (UI-saved keys, encrypted)
      2. .env environment variables           (legacy/admin fallback)
    """
    uid       = user_id or _get_user_id()
    cred_path = get_user_data_dir(uid) / "credentials.enc"
    if cred_path.exists():
        try:
            from auth.encryption import decrypt_dict
            return decrypt_dict(cred_path.read_text().strip())
        except Exception as e:
            import logging as _lg
            _lg.getLogger("celo_trader.config").warning(
                "Could not decrypt credentials for user %s: %s", uid, e
            )
    # Fallback to env vars (admin or unset users)
    return {
        "alpaca_api_key":     ALPACA_API_KEY,
        "alpaca_secret_key":  ALPACA_SECRET_KEY,
        "tradier_api_key":    TRADIER_API_KEY,
        "tradier_account_id": TRADIER_ACCOUNT_ID,
    }


def save_api_keys(keys: dict, user_id: str | None = None) -> None:
    """Encrypt and persist API keys for the user."""
    uid       = user_id or _get_user_id()
    cred_path = get_user_data_dir(uid) / "credentials.enc"
    from auth.encryption import encrypt_dict
    cred_path.write_text(encrypt_dict(keys))


def setup_logging() -> logging.Logger:
    """
    Shim kept for backward compatibility.
    Delegates to logger_config.setup_logging() which installs the
    production JSON formatter with RotatingFileHandler and secret redaction.
    """
    try:
        from logger_config import setup_logging as _setup
        return _setup(level=LOG_LEVEL)
    except ImportError:
        # Fallback: plain basicConfig if logger_config is somehow unavailable
        logging.basicConfig(
            level=LOG_LEVEL,
            format=LOG_FORMAT,
            handlers=[
                logging.StreamHandler(),
                logging.FileHandler(BASE_DIR / "log" / "bot.log", mode="a"),
            ],
        )
