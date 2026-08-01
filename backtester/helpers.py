"""
backtester/helpers.py — Free-function helpers shared across the
Backtester mixins: quiet-logging context manager, per-ticker IV lookup, and
the simplified option pricer used to simulate option premiums from the
underlying's price path.

Split out of the old single backtester.py (2026-08-01, file-size cleanup);
no logic changed, only relocated.
"""

import logging
import math
from contextlib import contextmanager

# ── Quiet logging for backtest replay ─────────────────────────────────────────
# Mirrors strategy_health/engine.py's identical helper (duplicated rather than
# imported to keep the two modules decoupled). A full backtest calls
# route_signals() thousands of times; without this, that writes a comparable
# number of INFO/DEBUG lines to bot.log — which the live dashboard's THINKING
# panel tails — making a backtest look like real-time trading activity and
# slowing the run down with unrelated disk I/O.
_NOISY_LOGGER_NAMES = ("celo_trader.strategy_router", "celo_trader.strategies", "celo_trader.router_gates")


@contextmanager
def _quiet_router_logging():
    loggers  = [logging.getLogger(name) for name in _NOISY_LOGGER_NAMES]
    previous = [lg.level for lg in loggers]
    try:
        for lg in loggers:
            lg.setLevel(logging.WARNING)
        yield
    finally:
        for lg, lvl in zip(loggers, previous):
            lg.setLevel(lvl)


# ── Per-ticker implied volatility lookup ──────────────────────────────────────
# Approximate annualised IV for each ticker.  Weekly contracts are priced on
# the market's expected move, not a fixed 0.60 that overstates SPY by 3-4×.
_TICKER_IV: dict[str, float] = {
    "SPY":  0.14, "QQQ":  0.18, "IWM":  0.22, "DIA":  0.14,
    "AAPL": 0.28, "MSFT": 0.26, "AMZN": 0.32, "GOOGL":0.30,
    "GOOG": 0.30, "META": 0.38, "NFLX": 0.42,
    "NVDA": 0.60, "AMD":  0.55, "TSLA": 0.72, "COIN": 0.85,
    "MSTR": 0.90, "PLTR": 0.65, "HOOD": 0.75,
    "JPM":  0.24, "GS":   0.28, "BAC":  0.28,
    "_default": 0.40,
}


def _get_iv(ticker: str) -> float:
    return _TICKER_IV.get(ticker.upper(), _TICKER_IV["_default"])


# ── Simplified option pricer ──────────────────────────────────────────────────

def _estimate_option_price(
    stock_price: float,
    strike: float,
    days_to_expiry: int = 5,
    iv: float = 0.40,
    option_type: str = "call",
) -> float:
    """
    Simplified Black-Scholes estimate with OTM moneyness discount.

    For ATM options: time_value ≈ stock × iv × sqrt(dte/252) × 0.4
    For OTM options: time_value decays via erfc as the strike moves away from
    the stock price, normalized by the 1-sigma expected move.  This reflects
    that a $3 OTM weekly costs less than a $6 ATM weekly even though both have
    zero intrinsic value — the ATM-only formula was overstating option costs
    by 2-3× and blocking valid contract sizing at small account balances.
    """
    if days_to_expiry <= 0:
        return max(0.0, stock_price - strike) if option_type == "call" \
               else max(0.0, strike - stock_price)

    intrinsic = (max(0.0, stock_price - strike) if option_type == "call"
                 else max(0.0, strike - stock_price))

    sqrt_t        = math.sqrt(days_to_expiry / 252)
    expected_move = stock_price * iv * sqrt_t            # 1-sigma expected move

    # Distance the strike sits OTM (0 for ITM/ATM options)
    otm_dist = (max(0.0, strike - stock_price) if option_type == "call"
                else max(0.0, stock_price - strike))

    # Normalize by expected move; erfc gives 1.0 at-the-money, decays to 0 deep OTM.
    # erfc(x * 1/√2) approximates 2·N(-x) which is the standard moneyness decay.
    otm_z            = otm_dist / max(expected_move, 0.01)
    moneyness_factor = math.erfc(otm_z * 0.7071)        # 0.7071 = 1/√2

    time_val = stock_price * iv * sqrt_t * 0.4 * moneyness_factor
    return round(max(intrinsic + time_val, 0.01), 2)


# OTM offset used when simulating strikes — 1.5% from the current stock price.
# The live bot buys weekly OTM options in the $2–4 range; the old "first $0.50
_SIMULATED_OTM_PCT: float = 0.015   # 1.5% OTM

# ── Simulated days-to-expiry (2026-07-23, DTE fidelity bug) ───────────────────
# CRITICAL FINDING: every _estimate_option_price() call site below was passing
# the LITERAL 5, not this constant — meaning every backtest this whole session
# priced options as if they were 5-DTE contracts. broker.py's real
# get_expirations() filters to 7-21 days out (`if 7 <= days_out <= 21`) and
# select_contract() takes the nearest one with a valid chain — so live trades
# a contract somewhere in that window, never 5. 10 is a documented
# approximation of "the nearest qualifying expiry," biased toward the front
# of the 7-21 range since select_contract() stops at the first match — NOT a
# precise empirical average. If you want to tighten this later, the real
# distribution is queryable from trades.expiry on live/paper fills.
_SIMULATED_DTE: int = 10


def _simulated_strike(stock_price: float, direction: str) -> float:
    """Strike 1.5% OTM, rounded to the nearest $0.50 increment."""
    if direction == "bullish":
        return math.ceil(stock_price * (1 + _SIMULATED_OTM_PCT) * 2) / 2
    return math.floor(stock_price * (1 - _SIMULATED_OTM_PCT) * 2) / 2


# ── Backtest engine ───────────────────────────────────────────────────────────
