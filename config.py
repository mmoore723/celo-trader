import os
import json
import logging
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env", override=True)

BASE_DIR      = Path(__file__).resolve().parent
_USER_DATA    = BASE_DIR / "user_data"           # per-user data root
DB_PATH       = BASE_DIR / "trades.db"           # legacy alias — kept so old imports don't break
DB_PATH_PAPER = BASE_DIR / "trades_paper.db"     # legacy — now per-user inside user_data/
DB_PATH_LIVE  = BASE_DIR / "trades_live.db"      # legacy — now per-user inside user_data/
LOG_PATH      = BASE_DIR / "log" / "bot.log"
SETTINGS_PATH = BASE_DIR / "user_settings.json"  # legacy single-user fallback


def _get_user_id() -> str:
    """
    Return the currently authenticated user's ID from the request-scoped ContextVar.
    Falls back to "admin" so all single-user / background-thread code is unchanged.
    """
    try:
        from auth.context import get_current_user_id
        return get_current_user_id()
    except Exception:
        return "admin"


def get_user_data_dir(user_id: str | None = None) -> Path:
    """Return the per-user data directory, creating it if needed."""
    uid = user_id or _get_user_id()
    p   = _USER_DATA / uid
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_db_path(user_id: str | None = None) -> Path:
    """
    Return the active SQLite database path for the given (or current) user.

    Hard separation:
      paper_trading = True  → trades_paper.db  (paper orders / sim trades)
      paper_trading = False → trades_live.db   (real broker fills ONLY)

    Reads settings dynamically so a live toggle takes effect immediately.
    """
    try:
        _s     = get_settings(user_id=user_id)
        _paper = _s.get("paper_trading", ALPACA_PAPER)
    except Exception:
        _paper = ALPACA_PAPER
    _dir  = get_user_data_dir(user_id)
    _name = "trades_paper.db" if _paper else "trades_live.db"
    return _dir / _name

ALPACA_API_KEY    = os.getenv("ALPACA_API_KEY", "")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY", "")
ALPACA_PAPER      = os.getenv("ALPACA_PAPER", "true").lower() == "true"
ALPACA_BASE_URL   = (
    "https://paper-api.alpaca.markets"
    if ALPACA_PAPER else "https://api.alpaca.markets"
)

TRADIER_API_KEY    = os.getenv("TRADIER_API_KEY", "")
TRADIER_BASE_URL   = os.getenv("TRADIER_BASE_URL", "https://api.tradier.com/v1")
TRADIER_ACCOUNT_ID = os.getenv("TRADIER_ACCOUNT_ID", "")
POLYGON_API_KEY    = os.getenv("POLYGON_API_KEY", "")

ALERT_EMAIL       = os.getenv("ALERT_EMAIL", "")
ALERT_SMTP_HOST   = os.getenv("ALERT_SMTP_HOST", "smtp.gmail.com")
ALERT_SMTP_PORT   = int(os.getenv("ALERT_SMTP_PORT", "587"))
ALERT_SMTP_USER   = os.getenv("ALERT_SMTP_USER", "")
ALERT_SMTP_PASS   = os.getenv("ALERT_SMTP_PASS", "")

STARTING_CAPITAL = 5000.0

# ── Concurrent position limit ─────────────────────────────────────────────────
# Maximum number of option positions the bot will hold open at the same time.
# Chosen by the user (2026-06-15) for a ~$5,000 account — lets the bot diversify
# across two setups instead of being all-or-nothing in one trade, without
# over-extending a small account's buying power across too many positions.
MAX_CONCURRENT_POSITIONS = 2

# ── 4-Tier Risk System ────────────────────────────────────────────────────────
# Growth mode ON:
#   balance < $5k   → Tier 4: 5%  (bootstrap — floors at 2 contracts when in this zone)
#   $5k–$25k        → Tier 3: 3%  (aggressive growth)
#   $25k–$50k       → Tier 2: 2%  (moderate transition)
#   balance ≥ $50k  → Tier 1: 1%  (auto-downgrade to preservation)
# Growth mode OFF (any balance) → Tier 1: 1%
# Daily loss hard cap is ALWAYS 10% — never overridden.
# At 5% on $2k: ~$109 risk/trade · ~2 full stops fires the 10% kill lock.

DAILY_LOSS_HARD_CAP_PCT   = 0.10   # 10% hard cap — non-negotiable, always enforced
BOOTSTRAP_RISK_PCT        = 0.05   # Tier 4: bootstrap 5% sub-$5k (reference constant)
GROWTH_MODE_RISK_PCT      = 0.03   # Tier 3: aggressive growth $5k–$25k
MID_TIER_RISK_PCT         = 0.02   # Tier 2: transition $25k–$50k
CONSERVATIVE_RISK_PCT     = 0.01   # Tier 1: capital preservation ≥$50k / growth OFF
GROWTH_RISK_BOUNDARY_BOOT = 5_000  # Tier 4 → Tier 3 boundary
GROWTH_RISK_BOUNDARY_LOW  = 25_000 # Tier 3 → Tier 2 boundary
GROWTH_RISK_BOUNDARY      = 50_000 # Tier 2 → Tier 1 boundary (auto-downgrade)
KILL_LOCK_HOURS           = 24     # hours to lock trading after daily hard cap fires

# ── R:R (Reward:Risk) Threshold Tiers ─────────────────────────────────────────
# The pre-entry R:R gate (RiskManager.evaluate_rr) compares the trade's computed
# reward:risk ratio against a minimum threshold. With the bot's fixed exit
# parameters (ORB_STAGE1_GAIN=0.50, ORB_STOP_PCT=0.30, SLIPPAGE_PCT=0.05) the
# R:R is ALWAYS ~1.269 — a constant, not a per-trade variable. A flat 1.6
# minimum therefore blocks 100% of trades on a small account.
#
# rr_ratio_mode (user_settings.json):
#   "auto"          → (DEFAULT) balance-based switch — uses MIN_RR_RATIO_SMALL_ACCOUNT
#                      while balance < GROWTH_RISK_BOUNDARY_BOOT (sub-$5k bootstrap
#                      tier), then automatically switches to
#                      MIN_RR_RATIO_PROFESSIONAL once balance crosses that boundary.
#   "small_account" → always use MIN_RR_RATIO_SMALL_ACCOUNT (1.2), regardless of balance.
#   "professional"  → always use MIN_RR_RATIO_PROFESSIONAL (1.6), regardless of balance.
MIN_RR_RATIO_SMALL_ACCOUNT = 1.2   # relaxed gate for sub-$5k bootstrap accounts
MIN_RR_RATIO_PROFESSIONAL  = 1.6   # standard gate once account graduates past bootstrap tier

# ── Manual risk override ──────────────────────────────────────────────────────
# When set to 0.01, 0.03, or 0.05 in user_settings.json this value takes
# precedence over the automatic balance-based tier logic in get_risk_tier().
# None (default) means "let the tier system decide".
# Accepted values: 0.01 (1%), 0.03 (3%), 0.05 (5%).  Any other value is ignored.
RISK_PER_TRADE: float | None = None
_VALID_RISK_OVERRIDES = {0.01, 0.03, 0.05}


def get_risk_tier(balance: float) -> float:
    """
    Return the effective risk % for a given account balance.

    Manual override (highest priority):
      If 'risk_per_trade' is set to 0.01, 0.03, or 0.05 in user_settings.json,
      that value is returned immediately — balance and growth_mode are ignored.

    Automatic tier logic (used when risk_per_trade is None / missing):
      Growth mode ON:
        balance < $5k    → 5%  (Tier 4, bootstrap)
        $5k ≤ bal < $25k → 3%  (Tier 3, aggressive growth)
        $25k ≤ bal < $50k→ 2%  (Tier 2, transition)
        balance ≥ $50k   → 1%  (Tier 1, auto-downgrade to preservation)
      Growth mode OFF → 1% always.
    """
    settings = get_settings()

    # ── Manual override: if explicitly set to a valid value, use it directly ──
    _override = settings.get("risk_per_trade")
    if _override is not None:
        try:
            _override_f = float(_override)
            if _override_f in _VALID_RISK_OVERRIDES:
                return _override_f
        except (TypeError, ValueError):
            pass  # fall through to automatic tier logic

    # ── Automatic tier logic ──────────────────────────────────────────────────
    if not settings.get("growth_mode", False):
        return CONSERVATIVE_RISK_PCT
    boundary_boot = float(settings.get("growth_risk_boundary_boot", GROWTH_RISK_BOUNDARY_BOOT))
    boundary_low  = float(settings.get("growth_risk_boundary_low",  GROWTH_RISK_BOUNDARY_LOW))
    boundary_high = float(settings.get("growth_risk_boundary",      GROWTH_RISK_BOUNDARY))
    if balance < boundary_boot:
        return BOOTSTRAP_RISK_PCT      # 5%  — sub-$5k bootstrap
    elif balance < boundary_low:
        return GROWTH_MODE_RISK_PCT    # 3%  — $5k–$25k growth
    elif balance < boundary_high:
        return MID_TIER_RISK_PCT       # 2%  — $25k–$50k transition
    else:
        return CONSERVATIVE_RISK_PCT   # 1%  — ≥$50k preservation


# ── Hyper-liquid index ETFs only — tightest spreads, deepest options liquidity
LIQUID_TICKERS = ["SPY", "QQQ"]

# Keep legacy name so existing code doesn't break
LARGE_CAP_TICKERS = LIQUID_TICKERS

# ── Hard-locked scanner universe (refactor 2026-06-16) ───────────────────────
# Only scan these 5 tickers. All have the tightest bid/ask spreads, deepest
# options chains on Tradier's free tier, and the highest intraday volume.
# No dynamic RVOL-ranked universe — keeps the bot focused and reduces noise.
TICKER_UNIVERSE = ["SPY", "QQQ", "AAPL", "NVDA", "TSLA"]

# ── Tiered time-box constants ────────────────────────────────────────────────
# Flat/losing trades are killed at EARLY_TIMEBOX_MIN to stop theta decay.
# MOMENTUM_DEAD_RVOL: if RVOL drops below this threshold AND the trade is
# losing, exit early — momentum has died and holding only burns theta.
# Both checks must pass: dead RVOL alone doesn't kill a trade that's working.
EARLY_TIMEBOX_MIN    = 60        # hard cap for flat/losing trades (extended from 30)
MOMENTUM_DEAD_RVOL   = 0.70      # RVOL floor — below this = institutional participation gone
                                 # 0.70 = 30% below average. Previous 1.0 fired on RVOL 0.95+
                                 # which is nearly normal volume — premature exits on valid setups.
MOMENTUM_DEAD_MIN    = 15        # earliest bar at which momentum-death check fires (min)

# ── Early momentum stop ───────────────────────────────────────────────────────
# If a trade is down within the first EARLY_TIMEBOX_MIN window, exit.
# Was 12% — but 5 DTE 1.5% OTM options with ~0.20 delta lose 12% from only
# a 0.22% adverse underlying move (SPY normal noise). Raised to 20% to match
# the hard stop floor so the early stop no longer creates a tighter-than-stop
# hair-trigger within the first hour. The dynamic hard stop (Exit 2) handles it.
EARLY_STOP_PCT    = 0.20         # -20% momentum stop (matches hard stop floor)

# ── Stage 2 trailing stop floor (refactor 2026-06-16) ────────────────────────
# After Stage 1 (+50% on 50%), the remainder's stop moves from break-even
# (entry_price × 1.00) up to entry_price × 1.15 — locks in a 15% profit floor
# instead of giving back all gains back to break-even.
STAGE2_TRAIL_PCT  = 0.15         # lock 15% profit on stage 2 remainder

# ── Hard session cutoff (refactor 2026-06-16) ────────────────────────────────
# At 3:55 PM ET: cancel all pending orders + market-close all open positions.
# Prevents holding through the final auction and closing-print spread blow-out.
SESSION_HARD_CUTOFF_HM = (15, 55)  # (hour, minute) in ET

RSI_PERIOD   = 14
RSI_OVERSOLD = 30
RSI_OVERBOUGHT = 70
MACD_FAST    = 12
MACD_SLOW    = 26
MACD_SIGNAL  = 9

TIMEFRAMES            = ["5Min", "15Min", "1Day"]
BACKTEST_MONTHS       = 3       # default look-back window for backtests
PENNY_TICKERS: list   = []      # tickers under $5 to skip (populated by broker)
DEFAULT_STOP_LOSS_PCT   = 0.50  # 50% stop loss on option premium
DEFAULT_TAKE_PROFIT_PCT = 1.00  # 100% take profit on option premium
REQUIRE_MTF_AGREEMENT = True   # default ON — user can disable in Risk Settings
MIN_OPEN_INTEREST     = 150
MAX_BID_ASK_SPREAD    = 0.50   # max spread — $0.02 was unrealistically tight for stock options
MIN_CONTRACT_COST     = 0.05   # min option premium ($5 per contract — avoids zero-value junk)
MAX_CONTRACT_COST     = 10.00  # max option premium — raised from $5 to fit JPM/NVDA/AAPL ATM chains
VOLUME_FILTER_MULTIPLIER = 1.2
EARNINGS_BLACKOUT_DAYS   = 2

# ── Commission (live trading only) ────────────────────────────────────────────
# Alpaca charges $0.65 per contract per leg.  Each round-trip (entry + exit)
# costs 2 legs, so total per trade = contracts × $0.65 × 2.
# Paper trading has zero commission — this constant is only applied when
# paper_trading = False in close_trade().
COMMISSION_PER_CONTRACT = 0.65

# Trading windows (ET) — full session: 09:30 open through 16:00 close
# Both phases use the same full-day window so afternoon momentum setups
# (e.g. 1:00–3:30 PM breakdowns/breakouts) are never blocked.
TRADING_WINDOWS_PHASE1 = [
    ("09:30", "16:00"),   # Full session — morning ORB through closing momentum
]
TRADING_WINDOWS_PHASE2 = [
    ("09:30", "16:00"),   # Full session — same; no phase split needed
]
# Active windows — auto-selected based on account balance
# trading_logic.py reads get_trading_windows() each tick
TRADING_WINDOWS = TRADING_WINDOWS_PHASE1  # default until balance confirmed


def get_trading_windows(balance: float = 0.0) -> list:
    """Return the correct trading windows based on account size."""
    phase2_boundary = _DEFAULTS.get("phase_2_boundary", 25000.0)
    if balance >= phase2_boundary:
        return TRADING_WINDOWS_PHASE2
    return TRADING_WINDOWS_PHASE1

LOG_LEVEL  = logging.INFO
LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"

_DEFAULTS = {
    # ── Risk Per Trade Override ────────────────────────────────────────────────
    # None = automatic (balance-based tier logic).
    # Set to 0.01, 0.03, or 0.05 to pin a specific risk % regardless of balance.
    "risk_per_trade": None,

    # ── Growth Mode ────────────────────────────────────────────────────────────
    "growth_mode":               False,     # OFF by default — user enables in Risk Settings
    "growth_risk_boundary_boot": 5_000.0,  # Tier 4 → Tier 3 transition (5% → 3%)
    "growth_risk_boundary_low":  25_000.0, # Tier 3 → Tier 2 transition (3% → 2%)
    "growth_risk_boundary":      50_000.0, # Tier 2 → Tier 1 transition (2% → 1%)
    "kill_lock_hours":           24,        # hours to lock after daily hard cap fires

    # ── R:R Threshold Mode ─────────────────────────────────────────────────────
    # "auto" (default) = balance-based switch: 1.2 R:R while < growth_risk_boundary_boot
    #   (sub-$5k bootstrap tier), auto-switches to 1.6 R:R once balance crosses it.
    # "small_account" = always 1.2 R:R. "professional" = always 1.6 R:R.
    "rr_ratio_mode":             "auto",

    # Dynamic Risk Ladder — no hard ceiling, scales with account
    "phase_1_aggressive_pct":   0.15,    # 15% sizing under $25k
    "phase_2_moderate_pct":     0.08,    # 8%  sizing $25k-$100k
    "phase_3_conservative_pct": 0.03,    # 3%  sizing above $100k
    "phase_2_boundary":         25000.0,
    "phase_3_boundary":         100000.0,
    "phase_3_hard_cap_usd":     5000.0,  # max single trade above $100k

    # Legacy sizing keys (used by dashboard sliders)
    "max_position_size_pct":    0.15,
    "max_position_dollars_pct": 15,
    "max_position_dollars":     750,

    # Exit parameters — max_daily_loss_pct is the user-adjustable soft limit.
    # DAILY_LOSS_HARD_CAP_PCT (10%) is enforced in code regardless of this setting.
    "max_daily_loss_pct":    0.10,   # default 10% — matches hard cap
    "stop_loss_pct":         0.50,
    "take_profit_pct":       1.00,
    "trail_stop_pct":        0.25,

    # Filters
    "volume_filter_enabled":   True,
    "volume_filter_multiplier": 2.0,
    "earnings_filter_enabled": True,
    "require_mtf_agreement":   True,
    "max_bid_ask_spread":      0.10,   # $0.10 max spread — realistic for liquid options

    # System
    "email_alerts_enabled": False,
    "paper_trading":        ALPACA_PAPER,
    "alpaca_data_plan":     "free",   # "free" = IEX regular session; "premium" = SIP + pre-market
    "trading_enabled":      True,
    "flip_trading_enabled": True,
    "last_known_balance":   0.0,
    "theme":                "light",
    "tax_reserve_pct":      25,
    "monthly_income_goal":  6000,
}


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
    return settings


def save_settings(updates: dict, user_id: str | None = None) -> None:
    uid     = user_id or _get_user_id()
    _path   = get_user_data_dir(uid) / "settings.json"
    current = get_settings(user_id=uid)
    current.update(updates)
    with open(_path, "w") as f:
        json.dump(current, f, indent=2)


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
        return logging.getLogger("celo_trader")