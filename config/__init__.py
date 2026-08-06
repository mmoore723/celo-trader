"""
config/__init__.py — Re-exports every public name from the old flat
config.py (549 lines, now split across paths.py, env_keys.py,
ai_settings.py, alerts.py, risk_constants.py, market_constants.py,
logging_settings.py, defaults.py, and settings_store.py) so every existing
`from config import X` call site across the app keeps working unchanged.

Split out of the old single config.py (2026-08-01, file-size cleanup); no
logic changed, only relocated. See config/paths.py's module docstring for
the BASE_DIR nesting-depth fix applied as part of this split.
"""

from config.paths import (
    BASE_DIR, _USER_DATA, DB_PATH, DB_PATH_PAPER, DB_PATH_LIVE,
    LOG_PATH, SETTINGS_PATH, SYSTEM_MAINTENANCE_PATH, _LEGACY_BOT_STATE_PATH,
    _get_user_id, get_user_data_dir, get_db_path, get_bot_state_path, load_bot_state_safely,
)

from config.env_keys import (
    ALPACA_API_KEY, ALPACA_SECRET_KEY, ALPACA_PAPER, ALPACA_BASE_URL,
    TRADIER_API_KEY, TRADIER_BASE_URL, TRADIER_ACCOUNT_ID,
    POLYGON_API_KEY, ANTHROPIC_API_KEY,
)

from config.ai_settings import (
    AI_REASONING_ENABLED, AI_NARRATION_MODEL, AI_NARRATION_TIMEOUT_SEC,
    AI_DECISION_SUPPORT_ENABLED, AI_DECISION_SUPPORT_ENABLED_LIVE,
    AI_DECISION_TIMEOUT_SEC, AI_DECISION_MODEL,
)

from config.alerts import (
    ALERT_EMAIL, ALERT_SMTP_HOST, ALERT_SMTP_PORT, ALERT_SMTP_USER, ALERT_SMTP_PASS,
)

from config.risk_constants import (
    STARTING_CAPITAL, MAX_CONCURRENT_POSITIONS, DAILY_LOSS_HARD_CAP_PCT,
    BOOTSTRAP_RISK_PCT, GROWTH_MODE_RISK_PCT, MID_TIER_RISK_PCT, CONSERVATIVE_RISK_PCT,
    GROWTH_RISK_BOUNDARY_BOOT, GROWTH_RISK_BOUNDARY_LOW, GROWTH_RISK_BOUNDARY,
    KILL_LOCK_HOURS, MIN_RR_RATIO_SMALL_ACCOUNT, MIN_RR_RATIO_PROFESSIONAL,
    RISK_PER_TRADE, get_risk_tier,
)

from config.market_constants import (
    LIQUID_TICKERS, LARGE_CAP_TICKERS, TICKER_UNIVERSE,
    EARLY_TIMEBOX_MIN, MOMENTUM_DEAD_RVOL, MOMENTUM_DEAD_MIN, MOMENTUM_DEAD_LOSS_PCT,
    EARLY_STOP_PCT, STAGE2_TRAIL_PCT, SESSION_HARD_CUTOFF_HM,
    RSI_PERIOD, RSI_OVERSOLD, RSI_OVERBOUGHT, MACD_FAST, MACD_SLOW, MACD_SIGNAL,
    TIMEFRAMES, BACKTEST_MONTHS, PENNY_TICKERS,
    DEFAULT_STOP_LOSS_PCT, DEFAULT_TAKE_PROFIT_PCT, REQUIRE_MTF_AGREEMENT,
    MIN_OPEN_INTEREST, MAX_BID_ASK_SPREAD, MIN_CONTRACT_COST, MAX_CONTRACT_COST,
    VOLUME_FILTER_MULTIPLIER, EARNINGS_BLACKOUT_DAYS, COMMISSION_PER_CONTRACT,
    TRADING_WINDOWS_PHASE1, TRADING_WINDOWS_PHASE2, TRADING_WINDOWS,
    get_trading_windows,
)

from config.logging_settings import LOG_LEVEL, LOG_FORMAT

from config.defaults import _DEFAULTS

from config.settings_store import (
    get_settings, save_settings, get_maintenance_state, save_maintenance_state,
    get_api_keys, save_api_keys, setup_logging,
)

__all__ = [
    "BASE_DIR", "_USER_DATA", "DB_PATH", "DB_PATH_PAPER", "DB_PATH_LIVE",
    "LOG_PATH", "SETTINGS_PATH", "SYSTEM_MAINTENANCE_PATH", "_LEGACY_BOT_STATE_PATH",
    "_get_user_id", "get_user_data_dir", "get_db_path", "get_bot_state_path", "load_bot_state_safely",
    "ALPACA_API_KEY", "ALPACA_SECRET_KEY", "ALPACA_PAPER", "ALPACA_BASE_URL",
    "TRADIER_API_KEY", "TRADIER_BASE_URL", "TRADIER_ACCOUNT_ID",
    "POLYGON_API_KEY", "ANTHROPIC_API_KEY",
    "AI_REASONING_ENABLED", "AI_NARRATION_MODEL", "AI_NARRATION_TIMEOUT_SEC",
    "AI_DECISION_SUPPORT_ENABLED", "AI_DECISION_SUPPORT_ENABLED_LIVE",
    "AI_DECISION_TIMEOUT_SEC", "AI_DECISION_MODEL",
    "ALERT_EMAIL", "ALERT_SMTP_HOST", "ALERT_SMTP_PORT", "ALERT_SMTP_USER", "ALERT_SMTP_PASS",
    "STARTING_CAPITAL", "MAX_CONCURRENT_POSITIONS", "DAILY_LOSS_HARD_CAP_PCT",
    "BOOTSTRAP_RISK_PCT", "GROWTH_MODE_RISK_PCT", "MID_TIER_RISK_PCT", "CONSERVATIVE_RISK_PCT",
    "GROWTH_RISK_BOUNDARY_BOOT", "GROWTH_RISK_BOUNDARY_LOW", "GROWTH_RISK_BOUNDARY",
    "KILL_LOCK_HOURS", "MIN_RR_RATIO_SMALL_ACCOUNT", "MIN_RR_RATIO_PROFESSIONAL",
    "RISK_PER_TRADE", "get_risk_tier",
    "LIQUID_TICKERS", "LARGE_CAP_TICKERS", "TICKER_UNIVERSE",
    "EARLY_TIMEBOX_MIN", "MOMENTUM_DEAD_RVOL", "MOMENTUM_DEAD_MIN", "MOMENTUM_DEAD_LOSS_PCT",
    "EARLY_STOP_PCT", "STAGE2_TRAIL_PCT", "SESSION_HARD_CUTOFF_HM",
    "RSI_PERIOD", "RSI_OVERSOLD", "RSI_OVERBOUGHT", "MACD_FAST", "MACD_SLOW", "MACD_SIGNAL",
    "TIMEFRAMES", "BACKTEST_MONTHS", "PENNY_TICKERS",
    "DEFAULT_STOP_LOSS_PCT", "DEFAULT_TAKE_PROFIT_PCT", "REQUIRE_MTF_AGREEMENT",
    "MIN_OPEN_INTEREST", "MAX_BID_ASK_SPREAD", "MIN_CONTRACT_COST", "MAX_CONTRACT_COST",
    "VOLUME_FILTER_MULTIPLIER", "EARNINGS_BLACKOUT_DAYS", "COMMISSION_PER_CONTRACT",
    "TRADING_WINDOWS_PHASE1", "TRADING_WINDOWS_PHASE2", "TRADING_WINDOWS",
    "get_trading_windows",
    "LOG_LEVEL", "LOG_FORMAT",
    "_DEFAULTS",
    "get_settings", "save_settings", "get_maintenance_state", "save_maintenance_state",
    "get_api_keys", "save_api_keys", "setup_logging",
]
