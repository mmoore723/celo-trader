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


_LEGACY_BOT_STATE_PATH = BASE_DIR / "bot_state.json"  # pre-multi-user location


def get_bot_state_path(user_id: str | None = None) -> Path:
    """
    Return the per-user bot_state.json path (user_data/{user_id}/bot_state.json),
    creating the user's data directory if needed.

    One-time migration: the very first time this is called for a user whose
    per-user file doesn't exist yet, if the legacy root-level bot_state.json
    exists, copy it in so existing "admin" state (account balance, open
    positions, etc.) isn't silently lost when this ships. Only ever applies
    once per user — after the copy, the per-user file is authoritative and
    the legacy file is left untouched (read-only fallback, never written).
    """
    _path = get_user_data_dir(user_id) / "bot_state.json"
    if not _path.exists() and _LEGACY_BOT_STATE_PATH.exists():
        try:
            _path.write_text(_LEGACY_BOT_STATE_PATH.read_text())
        except Exception:
            pass  # non-fatal — worst case the user starts with a fresh state file
    return _path

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

# Optional — used by strategy_health/ai_narrator.py (nightly audit summary)
# AND ai_reasoning/ (per-trade narration + phase-2 decision support below).
# Empty = every AI feature in the app silently skips itself and falls back
# to its free rule-based equivalent — nothing here is ever load-bearing.
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# ── AI reasoning layer (ai_reasoning/) ────────────────────────────────────────
# Phase 1: narration only. Feeds the feature snapshot the bot ALREADY computed
# for an entry/exit to Claude, purely to generate plain-English rationale for
# the THINKING panel/journal. Never gates a trade — narration runs on a
# background thread and its result (or failure) has zero effect on trading
# logic. Off by default; flip on once ANTHROPIC_API_KEY is set and you want
# to see it in action.
AI_REASONING_ENABLED     = os.getenv("AI_REASONING_ENABLED", "false").lower() == "true"
# Haiku, not Sonnet — this fires on every entry AND every exit (dozens/day
# once phase-2 tickers are added), unlike ai_narrator.py's once-daily Sonnet
# call. Plain-English rationale doesn't need frontier reasoning; Sonnet is
# reserved for phase-2 decision support where the stakes are higher.
AI_NARRATION_MODEL       = os.getenv("AI_NARRATION_MODEL", "claude-haiku-4-5-20251001")
# Generous on purpose: narration calls run fire-and-forget on a daemon thread
# (see ai_reasoning/narrator.py) and never block the trading loop, so this
# timeout only bounds how long a stray thread can live, not trade latency.
AI_NARRATION_TIMEOUT_SEC = int(os.getenv("AI_NARRATION_TIMEOUT_SEC", "10"))

# Phase 2 (decision support — veto/narrow an already-approved trade) is now
# built (ai_reasoning/decision_support.py) and, per explicit user decision
# 2026-07-20, turned on for PAPER TRADING ONLY to start building a track
# record before it's ever trusted near live capital. AI_DECISION_SUPPORT_
# ENABLED_LIVE is a SECOND, independent switch that stays hard off — decision
# support only ever runs in paper trading unless BOTH flags are true, so a
# single accidental flag flip can never expose live capital to it. Requires
# ANTHROPIC_API_KEY to be set in .env; if it isn't, this whole layer is a
# silent no-op regardless of this flag (see ai_reasoning/client.py).
AI_DECISION_SUPPORT_ENABLED      = os.getenv("AI_DECISION_SUPPORT_ENABLED", "true").lower() == "true"
AI_DECISION_SUPPORT_ENABLED_LIVE = os.getenv("AI_DECISION_SUPPORT_ENABLED_LIVE", "false").lower() == "true"
# Decision support (phase 2) is SYNCHRONOUS and sits in the entry path
# (unlike narration's fire-and-forget daemon thread), so its timeout bounds
# real trade latency, not just a stray thread's lifetime — kept short.
AI_DECISION_TIMEOUT_SEC = int(os.getenv("AI_DECISION_TIMEOUT_SEC", "4"))
# Sonnet, not Haiku — this is a real quality gate that can veto/narrow a
# live-capital trade (once the flags above are flipped on), unlike phase 1's
# plain-English narration. Worth the extra latency/cost for better judgment.
AI_DECISION_MODEL = os.getenv("AI_DECISION_MODEL", "claude-sonnet-4-5-20250929")

ALERT_EMAIL       = os.getenv("ALERT_EMAIL", "")
ALERT_SMTP_HOST   = os.getenv("ALERT_SMTP_HOST", "smtp.gmail.com")
ALERT_SMTP_PORT   = int(os.getenv("ALERT_SMTP_PORT", "587"))
ALERT_SMTP_USER   = os.getenv("ALERT_SMTP_USER", "")
ALERT_SMTP_PASS   = os.getenv("ALERT_SMTP_PASS", "")

STARTING_CAPITAL = 5000.0

# ── Concurrent position limit ─────────────────────────────────────────────────
# Maximum number of option positions the bot will hold open at the same time.
# Chosen by the user (2026-06-15) for a ~$5,000 account — lets the bot diversify
MAX_CONCURRENT_POSITIONS = 2

# ── 4-Tier Risk System ────────────────────────────────────────────────────────
# Growth mode ON:
#   balance < $5k   → Tier 4: 5%  (bootstrap — floors at 2 contracts when in this zone)

DAILY_LOSS_HARD_CAP_PCT   = 0.10   # 10% hard cap — fallback default only. As of
                                    # 2026-07-24 this is user-configurable via
                                    # Settings ("daily_loss_hard_cap_pct", stored as
                                    # a UI percentage e.g. 10.0 = 10%). risk.py reads
                                    # the settings value first and only falls back to
                                    # this constant if the key is somehow missing.
                                    # Small accounts trip this fast on normal option
                                    # premium swings — see the 7/21 + 7/22 back-to-back
                                    # kill-lock incident that motivated exposing it.
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
#   "auto"          → (DEFAULT) balance-based switch — uses MIN_RR_RATIO_SMALL_ACCOUNT
#   "small_account" → always use MIN_RR_RATIO_SMALL_ACCOUNT (1.2), regardless of balance.
#   "professional"  → always use MIN_RR_RATIO_PROFESSIONAL (1.6), regardless of balance.
MIN_RR_RATIO_SMALL_ACCOUNT = 1.2   # relaxed gate for sub-$5k bootstrap accounts
MIN_RR_RATIO_PROFESSIONAL  = 1.6   # standard gate once account graduates past bootstrap tier

# ── Manual risk override ──────────────────────────────────────────────────────
# When risk_per_trade is present in user_settings.json this value takes
# precedence over the automatic balance-based tier logic in get_risk_tier().
RISK_PER_TRADE: float | None = None


def get_risk_tier(balance: float) -> float:
    """
    Return the effective risk % for a given account balance.

    Manual override (highest priority):
      If 'risk_per_trade' is set in user_settings.json (0 < val <= 0.25),
      that value is returned immediately — balance and growth_mode are ignored.
      The Settings page saves risk_pct (e.g. 10) and converts to risk_per_trade
      (0.10) on POST so both keys are always in sync.

    Automatic tier logic (used when risk_per_trade is None / missing):
      Growth mode ON:
        balance < $5k    → 5%  (Tier 4, bootstrap)
        $5k ≤ bal < $25k → 3%  (Tier 3, aggressive growth)
        $25k ≤ bal < $50k→ 2%  (Tier 2, transition)
        balance ≥ $50k   → 1%  (Tier 1, auto-downgrade to preservation)
      Growth mode OFF → 1% always.
    """
    settings = get_settings()

    # ── Manual override: risk_per_trade (decimal) written by settings POST ────
    # Accepts any value in (0, 0.25] — previously the hard-coded set {0.01, 0.03,
    # 0.05} silently ignored any other value (including 0.10 for 10%).
    _override = settings.get("risk_per_trade")
    if _override is not None:
        try:
            _override_f = float(_override)
            if 0 < _override_f <= 0.25:   # sanity cap at 25%
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
TICKER_UNIVERSE = ["SPY", "QQQ", "AAPL", "NVDA", "TSLA"]

# ── Tiered time-box constants ────────────────────────────────────────────────
# Flat/losing trades are killed at EARLY_TIMEBOX_MIN to stop theta decay.
# MOMENTUM_DEAD_RVOL: if RVOL drops below this threshold AND the trade is
EARLY_TIMEBOX_MIN    = 60        # hard cap for flat/losing trades (extended from 30)
MOMENTUM_DEAD_RVOL   = 0.70      # RVOL floor — below this = institutional participation gone
                                 # 0.70 = 30% below average. Previous 1.0 fired on RVOL 0.95+
                                 # which is nearly normal volume — premature exits on valid setups.
MOMENTUM_DEAD_MIN    = 15        # earliest bar at which momentum-death check fires (min)
# 2026-07-15 audit: momentum_dead was firing on ANY losing trade because intraday
# volume declines mechanically after the open — rvol<0.70 midday is normal, not
# "dead". Require a real adverse move too: option must be down at least this %.
MOMENTUM_DEAD_LOSS_PCT = 0.10    # option must be down ≥10% for momentum-dead to fire

# ── Early momentum stop ───────────────────────────────────────────────────────
# If a trade is down within the first EARLY_TIMEBOX_MIN window, exit.
# Was 12% — but 5 DTE 1.5% OTM options with ~0.20 delta lose 12% from only
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
# 2026-07-15 audit: raised $0.05 → $0.80. Sub-$0.50 contracts (e.g. XLE $0.36 puts)
# have spreads of 5-15% of premium — a guaranteed round-trip loss.
MIN_CONTRACT_COST     = 0.80   # min option premium — avoids spread-death on cheap contracts
MAX_CONTRACT_COST     = 10.00  # max option premium — raised from $5 to fit JPM/NVDA/AAPL ATM chains
VOLUME_FILTER_MULTIPLIER = 1.2
EARNINGS_BLACKOUT_DAYS   = 2

# ── Commission (live trading only) ────────────────────────────────────────────
# Alpaca charges $0.65 per contract per leg.  Each round-trip (entry + exit)
# costs 2 legs, so total per trade = contracts × $0.65 × 2.
# paper_trading = False in close_trade().
COMMISSION_PER_CONTRACT = 0.65

# Trading windows (ET) — ENTRIES ONLY. Position management/exits run all session.
#
# FIX 2026-07-20: this used to be a two-session schedule (09:30-11:30 +
# 14:00-15:45) that blocked the 11:30-14:00 "lunch chop" period entirely.
# But MID_BRK's own session window is 10:30-13:00 and AFT_REV's is
# 13:00-15:30 — the old gate silently cut off 60% of MID_BRK's window
# (11:30-13:00) and 40% of AFT_REV's (13:00-14:00), because select_ticker()
# in trading/entry.py returns no ticker at all outside these windows, so
# those strategies' own evaluate() was never even reached during that time.
# Widened to one continuous window so every strategy's own session logic
# (not this global gate) is what decides whether a setup is good — per
# explicit user decision. Un-widening this back to a two-session schedule
# would silently re-break MID_BRK/AFT_REV the same way; if that's ever
# revisited, do it by trimming those strategies' own windows instead of
# narrowing this one, so the mismatch can't reappear silently.
TRADING_WINDOWS_PHASE1 = [
    ("09:30", "15:45"),
]
TRADING_WINDOWS_PHASE2 = [
    ("09:30", "15:45"),
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
    "max_daily_loss_pct":    0.10,   # default 10% — matches hard cap
    # Hard cap that triggers the 24h kill lock (trading fully frozen). Stored as
    # a UI percentage (10.0 = 10%), unlike max_daily_loss_pct above which is a
    # raw decimal — matches the other Settings-page fields' convention (see
    # orb_stage1_gain_pct etc. below). Added 2026-07-24 after two back-to-back
    # kill locks (7/21, 7/22) on a small account — was previously hardcoded and
    # non-adjustable (config.py's DAILY_LOSS_HARD_CAP_PCT).
    "daily_loss_hard_cap_pct": 10.0,

    # Minimum-grade entry filter — 2026-07-24, off by default. See
    # router_gates.py::apply_grade_filter(). Grades mirror the dashboard's
    # premarket report (A+/A/B/C/Watch); "C" cutoff blocks only "Watch".
    "min_grade_filter_enabled": False,
    "min_entry_grade": "C",
    "stop_loss_pct":         0.50,
    "take_profit_pct":       1.00,
    "trail_stop_pct":        0.25,

    # ── ORB trade parameters (user-editable via Settings → Trade Parameters) ────
    # These override the class constants in risk.py and the hardcoded gates in
    # entry.py / strategy_router.py so the user can tune live without touching code.
    "orb_stage1_gain_pct":   50,    # Stage-1 profit target as % of entry (50 = +50%)
                                    # NOTE 2026-07-21: this flat % is now only the FAIL-OPEN
                                    # fallback (used when ATR data is missing). The primary
                                    # stage-1 trigger is dynamic — see stage1_dynamic_enabled
                                    # below. Research basis: ab_test_stage1_target.py found
                                    # 50/30/20% all negative expectancy, ~0 winners ever
                                    # reached the static target.
    "orb_stop_loss_pct":     20,    # Option premium stop-loss as % of entry (20 = -20%)
    "stage1_dynamic_enabled":      True,   # ATR/momentum/volume-based stage1 trigger (kill-switch)
    "stage1_atr_target_mult":      2.0,    # ATR multiplier for the dynamic target (1.5-2.5x per research)
    "stage1_min_lock_floor_pct":   10,     # min gain % before momentum/volume fade can trigger early lock
    "stage1_rvol_fade_threshold":  1.0,    # RVOL below this (after being elevated) = crowd left, lock early
    "stage1_momentum_require_both": False, # False=RSI OR MACD fires early lock, True=requires BOTH (untested candidate)
    # 2026-07-15 audit: 25% was far too loose — a 25% spread is an instant ~12%
    # loss at entry. 8% max keeps round-trip spread cost survivable.
    "spread_gate_pct":       8,     # Max bid-ask spread as % of mid (8 = 8%)
    "vol_roc_threshold":     0.50,  # Volume ROC veto threshold (0.50 = 50% of prior vol)
    # 2026-07-22: ab_test_exit_complexity.py — stripped-down 3-rule exit
    # (hard stop / 3.0x chandelier trail / 1 time cap) beat the full 9+-
    # condition engine on realized R:R (1.17-1.29x vs 0.20-0.27x) at roughly
    # the same avg loss but 4.3x bigger avg wins, stacked with prior_swing.
    # Default True = simplified path live. False = fall back to the full
    # risk.py engine (trading/position_manager.py's should_exit() call).
    "simplified_exit_mode":  True,

    # 2026-07-23 (Gap 3, professional-strategy-alignment audit): live 1Hour
    # MTF confirmation gate — see trading/mtf_live_gate.py + router_gates.py's
    # apply_mtf_confirmation(). OFF by default because, unlike every other
    # toggle in this file, it can't be validated against the historical
    # backtester (it depends on a live "as-of-now" API fetch, not replayable
    # multi-day data) — watch it in signal_only_mode before trusting it.
    "mtf_confirmation_enabled": True,

    # 2026-07-31: INST_ORB immediate-entry (skip retest wait) toggle — see
    # strategies/inst_orb.py and api/models.py's field comment. ON by default
    # per explicit user decision.
    "strategy_instorb_immediate_entry": True,

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