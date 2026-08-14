"""
config/market_constants.py — Ticker universe, exit-timing constants,
indicator periods, timeframes, contract/spread gates, and the trading
windows (incl. get_trading_windows()).

Split out of the old single config.py (2026-08-01, file-size cleanup); no
logic changed, only relocated.
"""

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
# The global window remains continuous; each approved strategy owns its
# narrower, independently tested session window.
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
    # Lazy import: defaults._DEFAULTS lives in config/defaults.py, which does
    # not import this module, so this isn't strictly circular — kept lazy
    # anyway to match the get_settings()-style pattern used elsewhere in the
    # config package and to avoid import-order surprises from __init__.py.
    from config.defaults import _DEFAULTS
    phase2_boundary = _DEFAULTS.get("phase_2_boundary", 25000.0)
    if balance >= phase2_boundary:
        return TRADING_WINDOWS_PHASE2
    return TRADING_WINDOWS_PHASE1
