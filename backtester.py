"""
backtester.py — Full-Strategy Historical Simulation Engine.

Replays N months of historical 5-min OHLCV bars through all live strategy
modules using the SAME quality gates, sizing, and exit logic as the live bot
(confidence floor, conflict veto, ADX regime gate, session windows, 4-tier
risk ladder, staged exits, 5% slippage per side).

Output: overall P&L / win rate / Sharpe / drawdown, per-strategy breakdown,
daily P&L, exit-reason breakdown, and full trade log.
"""

import logging
import math
from contextlib import contextmanager
from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd

from config import (
    BACKTEST_MONTHS, STARTING_CAPITAL,
    EARLY_TIMEBOX_MIN, EARLY_STOP_PCT, STAGE2_TRAIL_PCT,
    MOMENTUM_DEAD_RVOL, MOMENTUM_DEAD_MIN,
    get_trading_windows as _get_trading_windows,
    _DEFAULTS,
)
from signals import (
    bars_to_df, compute_vwap_bands, compute_rvol,
    get_opening_range, ORB_RVOL_THRESHOLD,
)
from risk import RiskManager
from backtest_exit_sim import ExitSimState, evaluate_bt_exit
from backtest_exit_sim_simplified import evaluate_bt_exit_simplified

# 2026-07-21 integration: entry detection now calls the REAL router instead
# of a hand-copied gate stack (see _simulate_day docstring + diag_entry_
# resolution_comparison.py for why). ADX_MIN/compute_adx_series are kept
# only for an informational chop-bar diagnostic counter, not for gating —
# route_signals() does its own ADX gating internally now.
from strategy_router import route_signals
from regime_manager import ADX_MIN, compute_adx_series
from backtester_1min_entry import fetch_1min_entry_data
import backtest_data_cache

logger = logging.getLogger("celo_trader.backtester")


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

class Backtester:
    """
    Runs ALL 8 live strategy modules on historical 5-min bars using the
    SAME entry filters and exit logic as the live trading bot.

    Parameters
    ----------
    alpaca           : AlpacaClient (or any object with .get_bars())
    ticker           : stock symbol to test
    months           : look-back period in months
    starting_capital : initial simulated account balance
    direction        : "both" | "calls_only" | "puts_only"
    risk_pct         : override risk % (e.g. 0.05 for 5%). None = use live tier ladder.
    """

    # Mirror the constants from RiskManager so they're always in sync.
    # CLEANUP 2026-07-22 (full-audit finding 1.4): a dead ORB_STAGE1_GAIN
    # class-level mirror used to live here, permanently stuck at
    # RiskManager's raw class default (0.25) and never read anywhere —
    # the real, live-synced value is self._risk.ORB_STAGE1_GAIN (see
    # __init__). Removed to avoid a future edit assuming self.ORB_STAGE1_GAIN
    # is synced the way self._risk.ORB_STAGE1_GAIN is.
    ORB_STOP_PCT          = RiskManager.ORB_STOP_PCT           # 0.20
    ORB_TIME_BOX_WINNER   = RiskManager.ORB_TIME_BOX_WINNER    # 90 min
    SLIPPAGE_PCT          = RiskManager.SLIPPAGE_PCT           # 0.05
    STOP_TIGHTEN_INTERVAL = RiskManager.STOP_TIGHTEN_INTERVAL  # 15 min
    STOP_TIGHTEN_STEP     = RiskManager.STOP_TIGHTEN_STEP      # 0.05
    STOP_FLOOR_PCT        = RiskManager.STOP_FLOOR_PCT         # 0.10

    # 2026-07-22: fidelity fix — live has always gated entries on R:R via
    # risk.evaluate_rr(), the backtester never did. True = match live.
    # See ab_test_rr_gate.py for the case this gets toggled off.
    RR_GATE_ENABLED       = True

    # 2026-07-22: speed fix — route_signals() was being fed the ENTIRE
    # multi-day history since day 1 on every single tick (bar_slice grows
    # unbounded), making per-tick cost grow across the whole backtest —
    # O(days²) overall. The only thing inside route_signals() that reads
    # more than the current day is compute_rvol(df, lookback_days=10) in
    # signals.py, which only needs ~10 trading days. 20 is a safety margin.
    # Capping the slice to a trailing window turns that back into O(days).
    ENTRY_LOOKBACK_DAYS   = 20

    # 2026-07-22: exit-complexity A/B test. False = current 9+-condition
    # exit stack (backtest_exit_sim.py). True = the stripped-down 3-rule
    # exit (hard stop / 3.0x chandelier trail / one time cap, see
    # backtest_exit_sim_simplified.py). See ab_test_exit_complexity.py.
    SIMPLIFIED_EXIT_MODE  = False

    def __init__(
        self,
        alpaca,
        ticker: str,
        months: int = BACKTEST_MONTHS,
        starting_capital: float = STARTING_CAPITAL,
        direction: str = "both",
        risk_pct: Optional[float] = None,
    ):
        self.alpaca            = alpaca
        self.ticker            = ticker
        self.months            = months
        self.capital           = starting_capital
        self.direction         = direction
        self.risk_pct_override = risk_pct   # None → live 4-tier ladder
        self.trades: list[dict] = []
        # Used for structural_stop_from_level()/should_exit() AND (2026-07-22)
        # the pre-entry evaluate_rr() gate — the same real risk.py engine live
        # trading calls (see backtest_exit_sim.py).
        self._risk = RiskManager()
        # BUG FIX 2026-07-22: risk.py's class default (ORB_STAGE1_GAIN=0.25) is
        # stale — live overrides it every tick from settings (orb_stage1_gain_pct,
        # default 50 in config.py's _DEFAULTS). backtest_exit_sim.py's own _risk
        # instance already got this same fix on 2026-07-21; this Backtester's
        # self._risk never did. Left uncorrected, evaluate_rr()'s rr_ratio is a
        # mathematically constant 0.781 (every term scales with entry price, so
        # only these two percentages determine it) — permanently below the
        # 1.2x/1.6x gate, blocking every single trade regardless of ticker,
        # strategy, or entry quality. This is why the R:R-gated backtest and
        # ab_test_structural_stop_mode.py runs came back with 0 trades.
        self._risk.ORB_STAGE1_GAIN = float(_DEFAULTS.get("orb_stage1_gain_pct", 50)) / 100.0
        self._risk.ORB_STOP_PCT    = float(_DEFAULTS.get("orb_stop_loss_pct", 20)) / 100.0
        # BUG FIX 2026-07-22 (full-audit finding 1.1): the two lines above only
        # synced 2 of the 7 knobs live actually syncs every tick (see
        # trading/entry.py's "Sync user-editable trade parameters" block).
        # The other 5 were silently left at risk.py's raw class defaults —
        # correct today only by coincidence, not by design. If any of these
        # is ever changed via Settings, an unpatched backtester would keep
        # testing the OLD value forever with no error. Syncing all 7 here.
        self._risk.STAGE1_DYNAMIC_ENABLED     = bool(_DEFAULTS.get("stage1_dynamic_enabled", True))
        self._risk.STAGE1_ATR_TARGET_MULT     = float(_DEFAULTS.get("stage1_atr_target_mult", 2.0))
        self._risk.STAGE1_FLOOR_FRACTION_OF_TARGET = float(_DEFAULTS.get("stage1_floor_fraction_of_target", 45)) / 100.0
        self._risk.STAGE1_RVOL_FADE_THRESHOLD = float(_DEFAULTS.get("stage1_rvol_fade_threshold", 1.0))
        self._risk.STAGE1_MOMENTUM_REQUIRE_BOTH = bool(_DEFAULTS.get("stage1_momentum_require_both", True))
        # Entry-detection sources — populated by _prep_entry_sources() in run().
        self._df1m: Optional[pd.DataFrame] = None
        self._1m_day_start: dict = {}
        self._df5m_full: Optional[pd.DataFrame] = None
        self._5m_day_start: dict = {}

    # ── Contract sizing helper ────────────────────────────────────────────────

    def _size_contracts(self, balance: float, entry_px: float) -> int:
        """
        Size using live bot's contract formula.

        Replicates RiskManager.calculate_contracts() exactly, with an optional
        risk_pct override so the backtester can test any flat rate.

        Formula: floor( (balance × risk_pct) / (entry_px × ORB_STOP_PCT × 100) )
        Min 1 contract if budget allows; notional capped at 20–30% of balance.
        """
        if entry_px <= 0 or balance <= 0:
            return 0

        # Determine effective risk % — override takes priority over live tier logic
        if self.risk_pct_override is not None:
            risk_pct = float(self.risk_pct_override)
        else:
            # Use the live bot's 4-tier ladder based on current simulated balance
            _rm_temp = RiskManager(account_balance=balance)
            risk_pct = _rm_temp.effective_risk_pct(balance)

        total_risk        = balance * risk_pct
        risk_per_contract = entry_px * self.ORB_STOP_PCT * 100   # $ at risk per contract

        if risk_per_contract <= 0:
            return 0

        contracts = int(total_risk / risk_per_contract)

        # Notional cap: 30% of balance in high-risk tiers, 20% in conservative
        max_notional_pct = 0.30 if risk_pct > 0.01 else 0.20
        max_notional     = balance * max_notional_pct

        # Floor to 1 contract if we can afford the PREMIUM (notional check).
        # The risk-based floor (risk_per_contract <= total_risk) is too strict
        # for small accounts trading expensive underlyings like SPY — the live
        if contracts == 0 and (entry_px * 100) <= max_notional:
            contracts = 1

        while contracts > 1 and (entry_px * 100 * contracts) > max_notional:
            contracts -= 1

        return max(0, contracts)

    # ── Extra-timeframe fetch (2026-07-21, for the dynamic ATR-trail multiplier) ─
    # Live position_manager.py doesn't use a flat trail multiplier — it widens
    # or tightens the ATR trail based on 1-hour trend bias and 15-min swing
    # proximity (plus 5-min RSI/MACD, which the primary 5m `df` already
    # covers). The backtester used to skip this and use a flat 2.0x base —
    # disclosed as a known gap. This fetches those two extra timeframes so
    # backtest_exit_sim.py can replicate the REAL adaptive multiplier instead
    # of a static stand-in. Best-effort: any failure here just means the
    # trail falls back to the flat 2.0x base, same as before — never fatal.
    def _fetch_extra_timeframe(self, interval: str, start_d: str, end_d: str) -> pd.DataFrame:
        # FIX 2026-07-31 (backtest speed/reliability): Alpaca tried first —
        # same reasoning as the primary 5-min fetch above. get_bars() maps
        # "1h"/"15m" to Alpaca's "1Hour"/"15Min" and already has a real,
        # working 10s timeout. yfinance only runs if Alpaca comes back empty.
        _alpaca_tf = {"1h": "1Hour", "15m": "15Min"}.get(interval)
        if _alpaca_tf:
            try:
                raw = self.alpaca.get_bars(self.ticker, _alpaca_tf, limit=2000)
                bars = raw[0] if isinstance(raw, tuple) else raw
                if bars:
                    _df = bars_to_df(bars)
                    if not _df.empty:
                        logger.info("Backtest: Alpaca returned %d %s bars for %s",
                                    len(_df), interval, self.ticker)
                        return _df
            except Exception as _al_ex:
                logger.warning("Backtest: Alpaca %s fetch failed for %s: %s",
                                interval, self.ticker, _al_ex)

        try:
            import yfinance as yf
            import concurrent.futures as _cf

            def _do_download():
                return yf.download(
                    self.ticker, start=start_d, end=end_d,
                    interval=interval, progress=False, auto_adjust=True,
                )

            # FIX 2026-07-31: `with ThreadPoolExecutor(...)` was cosmetic here —
            # exiting the `with` block calls shutdown(wait=True), which BLOCKS
            # until the background thread actually finishes, even after the
            # .result(timeout=20) above it already timed out. If yf.download()
            # truly hangs (TCP connects but never receives data — no error, no
            # exception, just silence), the process still blocks forever on
            # exit, defeating the timeout entirely. Confirmed live: a run on
            # the user's Mac hung with no output for 16+ minutes and didn't
            # even respond to Ctrl+C (blocked in a native thread-join, not
            # Python bytecode). Managing the executor manually and calling
            # shutdown(wait=False) on timeout lets the main thread move on —
            # the stuck background thread is abandoned, not force-killed
            # (Python can't kill threads), but it no longer blocks anything.
            _ex = _cf.ThreadPoolExecutor(max_workers=1)
            _fut = _ex.submit(_do_download)
            try:
                _raw = _fut.result(timeout=20)
            except _cf.TimeoutError:
                logger.warning("Backtest: yfinance %s timed out for %s", interval, self.ticker)
                _ex.shutdown(wait=False)
                return pd.DataFrame()
            _ex.shutdown(wait=False)

            if _raw.empty:
                return pd.DataFrame()
            if hasattr(_raw.columns, "get_level_values"):
                _raw.columns = _raw.columns.get_level_values(0)
            _raw = _raw.rename(columns={
                "Open": "open", "High": "high", "Low": "low",
                "Close": "close", "Volume": "volume",
            })
            _raw.index.name = "time"
            _raw = _raw.reset_index()
            _raw["time"] = (
                pd.to_datetime(_raw["time"], utc=True)
                .dt.tz_convert("America/New_York")
                .dt.tz_localize(None)
            )
            return _raw[["time", "open", "high", "low", "close", "volume"]].copy()
        except Exception as _ex:
            logger.warning("Backtest: %s fetch failed for %s: %s", interval, self.ticker, _ex)
            return pd.DataFrame()

    # ── Entry-detection source prep (2026-07-21 integration) ─────────────────

    def _prep_entry_sources(self, df5_session: pd.DataFrame) -> None:
        """
        Prepare both possible entry-detection sources for _simulate_day():
        1-minute bars where Alpaca has coverage, and the full multi-day
        5-minute frame (session-filtered, indicators already attached) as a
        fallback for days outside that window. Both are stored as single
        sorted frames with a per-date starting row index so _simulate_day()
        can slice "all history up to now" in O(1) — needed because real
        RVOL (compute_rvol's 10-day lookback) requires multi-day context,
        not just the current day.

        WHY 1-MIN AT ALL: diag_entry_resolution_comparison.py found the
        1-min view caught a signal the 5-min view missed ENTIRELY on 8 of 17
        SPY days (47%) — a bigger, more clearly evidenced effect than any of
        the threshold tuning done earlier this session. Falling back to
        5-min for days outside Alpaca's ~18-trading-day 1-min window (see
        backtester_1min_entry.py) keeps the full backtest date range intact
        instead of shrinking every run down to 18 days.
        """
        self._df5m_full = df5_session
        self._5m_day_start = {
            d: int(grp.index[0]) for d, grp in df5_session.groupby("_date")
        }

        self._df1m = None
        self._1m_day_start = {}
        try:
            raw = fetch_1min_entry_data(self.alpaca, self.ticker, months=self.months)
            if raw is None or raw.empty:
                logger.info("Backtest: no 1-min data for %s — every day uses 5-min entries", self.ticker)
                return
            mask = (
                (raw["time"].dt.hour > 9) |
                ((raw["time"].dt.hour == 9) & (raw["time"].dt.minute >= 30))
            ) & (raw["time"].dt.hour < 16)
            df1m = raw[mask].sort_values("time").reset_index(drop=True)
            if df1m.empty:
                return
            self._1m_day_start = {
                d: int(grp.index[0]) for d, grp in df1m.groupby("_date")
            }
            self._df1m = df1m
            logger.info(
                "Backtest: 1-min entry data for %s — %d bars across %d days "
                "(5-min fallback for the rest)",
                self.ticker, len(df1m), len(self._1m_day_start),
            )
        except Exception as ex:
            logger.warning(
                "1-min entry fetch failed for %s (%s) — every day uses 5-min entries",
                self.ticker, ex,
            )

    # ── Market data fetch + precompute (cached, see backtest_data_cache.py) ───

    def _load_market_data(self):
        """
        Fetch 5-min/1h/15m/1-min bars, precompute indicators (RVOL/EMA50/ATR/
        ADX), and prep the entry-detection sources — OR, on a same-day cache
        hit, skip all of that and restore it from disk in milliseconds.

        WHY CACHED (2026-07-22): A/B test scripts construct a fresh Backtester
        per ticker, once per variant (4-5x per run). The candles don't change
        between variants — only the strategy logic does — so re-fetching and
        re-computing indicators on identical data every variant was pure
        waste. See backtest_data_cache.py's module docstring.

        Returns either the precomputed df (success) or {"error": ...} (same
        failure cases the old inline code returned early on).
        """
        # FIX 2026-07-23: key the cache by the EFFECTIVE fetch window, not the
        # raw `months` value — see backtest_data_cache.py's module docstring.
        # months=2 and months=3 (and any months>=2) both resolve to the same
        # 59-day yfinance cap below, so they now share one cache entry instead
        # of each script re-fetching identical candles under a different key.
        _cache_max_days = backtest_data_cache.max_days_for(self.months)
        bundle = backtest_data_cache.load(self.ticker, _cache_max_days)
        if bundle is not None:
            self._df_1h        = bundle["df_1h"]
            self._df_15m       = bundle["df_15m"]
            self._df1m         = bundle["df1m"]
            self._1m_day_start = bundle["day1m_start"]
            self._df5m_full    = bundle["df5m_full"]
            self._5m_day_start = bundle["day5m_start"]
            return bundle["df"]

        # ── Fetch historical 5-min bars ───────────────────────────────────────
        # FIX 2026-07-31 (backtest speed/reliability): Alpaca is now tried
        # FIRST, yfinance is the fallback — this used to be the other way
        # around. Reasoning: Alpaca is what live trading already uses every
        # day, its requests all carry a real, working 10s timeout (broker.py's
        # _get()), and it has no 60-day depth cap the way yfinance's 5-min
        # bars do. yfinance (via curl_cffi) has caused two real incidents —
        # a hard network refusal in one environment, and a 16+ minute silent
        # hang on the user's Mac that didn't even respond to Ctrl+C (see the
        # ThreadPoolExecutor fix above/below). It's kept as a fallback only,
        # not removed, in case Alpaca's free IEX feed is ever missing a bar.
        import datetime as _dt
        _today    = _dt.date.today()
        _max_days = min(self.months * 30, 59)   # yfinance 5m hard limit = 60 d — Alpaca has no such cap
        _start_d  = (_today - _dt.timedelta(days=_max_days)).strftime("%Y-%m-%d")
        _end_d    = (_today + _dt.timedelta(days=1)).strftime("%Y-%m-%d")

        df = pd.DataFrame()
        _data_source = None
        try:
            raw = self.alpaca.get_bars(self.ticker, "5Min", limit=10000)
            bars_5m = raw[0] if isinstance(raw, tuple) else raw
            if bars_5m:
                df = bars_to_df(bars_5m)
                if not df.empty:
                    # DEPTH CHECK (2026-07-31): a non-empty result isn't the
                    # same as a COMPLETE one. Alpaca's free IEX feed has a
                    # known quirk of sometimes returning only recent bars
                    # (see broker.py get_session_bars()'s "sometimes returns
                    # only recent bars" comment, a same-day version of this
                    # same risk) — if that happens here too, treating any
                    # non-empty df as "good" would silently run the backtest
                    # over a shorter, wrong window instead of the requested
                    # one. Require the earliest returned bar to be within
                    # 20% of the requested start date; otherwise the data is
                    # too shallow and yfinance takes over instead.
                    _earliest = df["time"].min().date()
                    _requested_start = _dt.date.fromisoformat(_start_d)
                    _slack_days = max(3, int(_max_days * 0.20))
                    if _earliest > _requested_start + _dt.timedelta(days=_slack_days):
                        logger.warning(
                            "Backtest: Alpaca 5m data for %s only goes back to %s "
                            "(requested %s) — too shallow, falling back to yfinance",
                            self.ticker, _earliest, _start_d,
                        )
                        df = pd.DataFrame()
                    else:
                        _data_source = "alpaca"
                        logger.info("Backtest: Alpaca returned %d 5m bars for %s (from %s)",
                                    len(df), self.ticker, _earliest)
        except Exception as _al_ex:
            logger.warning("Backtest: Alpaca 5m fetch failed for %s: %s", self.ticker, _al_ex)

        # yfinance fallback — same 20/30s non-blocking timeout pattern as
        # _fetch_extra_timeframe() below (shutdown(wait=False) so a hang
        # can't block the process even here).
        if df.empty:
            try:
                import yfinance as yf
                import concurrent.futures as _cf

                def _do_download():
                    return yf.download(
                        self.ticker,
                        start=_start_d,
                        end=_end_d,
                        interval="5m",
                        progress=False,
                        auto_adjust=True,
                    )

                _ex = _cf.ThreadPoolExecutor(max_workers=1)
                _fut = _ex.submit(_do_download)
                try:
                    _raw_yf = _fut.result(timeout=30)
                except _cf.TimeoutError:
                    logger.warning("Backtest: yfinance timed out after 30s for %s", self.ticker)
                    _raw_yf = pd.DataFrame()
                _ex.shutdown(wait=False)

                if not _raw_yf.empty:
                    if hasattr(_raw_yf.columns, "get_level_values"):
                        _raw_yf.columns = _raw_yf.columns.get_level_values(0)
                    _raw_yf = _raw_yf.rename(columns={
                        "Open": "open", "High": "high",
                        "Low": "low", "Close": "close", "Volume": "volume",
                    })
                    _raw_yf.index.name = "time"
                    _raw_yf = _raw_yf.reset_index()
                    _raw_yf["time"] = (
                        pd.to_datetime(_raw_yf["time"], utc=True)
                        .dt.tz_convert("America/New_York")
                        .dt.tz_localize(None)
                    )
                    df = _raw_yf[["time", "open", "high", "low", "close", "volume"]].copy()
                    _data_source = "yfinance"
                    logger.info(
                        "Backtest: yfinance returned %d 5m bars for %s (%s → %s)",
                        len(df), self.ticker, _start_d, _end_d,
                    )
            except Exception as _yf_ex:
                logger.warning("Backtest: yfinance failed for %s: %s", self.ticker, _yf_ex)

        if df.empty:
            return {"error": f"No historical data for {self.ticker}"}
        self._data_source = _data_source or "unknown"

        # Trim to requested look-back window
        cutoff = pd.Timestamp.now() - pd.DateOffset(months=self.months)
        df = df[df["time"] >= cutoff].reset_index(drop=True)

        if df.empty:
            return {"error": f"No bars within the last {self.months} months "
                    "(5-minute bars are limited to ~60 days; try 1–2 months)"}

        # 1h/15m fetch for the real dynamic trail multiplier (see
        # _fetch_extra_timeframe's docstring). 15m shares 5m's ~60-day yfinance
        # cap; 1h supports ~730 days so the same window is always covered.
        self._df_1h  = self._fetch_extra_timeframe("1h",  _start_d, _end_d)
        self._df_15m = self._fetch_extra_timeframe("15m", _start_d, _end_d)
        logger.info(
            "Backtest: extra-timeframe fetch for %s — 1h=%d bars, 15m=%d bars",
            self.ticker, len(self._df_1h), len(self._df_15m),
        )

        # Pre-compute indicators across the full dataset
        df["rvol"]  = compute_rvol(df, lookback_days=10)
        df["ema50"] = df["close"].ewm(span=50, adjust=False).mean()
        hl  = df["high"]  - df["low"]
        hcp = (df["high"]  - df["close"].shift(1)).abs()
        lcp = (df["low"]   - df["close"].shift(1)).abs()
        tr  = pd.concat([hl, hcp, lcp], axis=1).max(axis=1)
        df["atr"] = tr.ewm(span=14, adjust=False).mean()

        df["_date"] = df["time"].dt.date

        # ── ADX(14) series — informational only now (2026-07-21) ─────────────
        # route_signals() does its own ADX gating internally; this is kept
        # purely so the diagnostics dict can still report a chop-bar count.
        try:
            _adx_s = compute_adx_series(df)
            if _adx_s is not None:
                df["adx"] = _adx_s.reindex(df["time"].dt.floor("5min")).to_numpy()
        except Exception as _adx_ex:
            logger.debug("ADX series unavailable: %s", _adx_ex)

        # ── Entry-detection sources (2026-07-21 integration) ─────────────────
        # Full multi-day 5-min frame, session-filtered, for the fallback path;
        # fetch_1min_entry_data() inside handles the 1-min side. See
        # _prep_entry_sources()'s docstring for why this exists.
        _full_session_mask = (
            (df["time"].dt.hour > 9) |
            ((df["time"].dt.hour == 9) & (df["time"].dt.minute >= 30))
        ) & (df["time"].dt.hour < 16)
        self._prep_entry_sources(df[_full_session_mask].reset_index(drop=True))

        backtest_data_cache.save(
            self.ticker, _cache_max_days,
            df=df, df_1h=self._df_1h, df_15m=self._df_15m,
            df1m=self._df1m, day1m_start=self._1m_day_start,
            df5m_full=self._df5m_full, day5m_start=self._5m_day_start,
        )
        return df

    # ── Public entry point ────────────────────────────────────────────────────

    def run(self) -> dict:
        """Execute the full multi-strategy backtest. Returns a results dict."""
        logger.info(
            "backtest_start",
            extra={
                "event":        "backtest_start",
                "ticker":       self.ticker,
                "months":       self.months,
                "capital":      self.capital,
                "risk_pct":     self.risk_pct_override,
            },
        )

        df = self._load_market_data()
        if isinstance(df, dict):   # error case — see _load_market_data()
            return df

        balance      = self.capital
        daily_pnl: dict[str, float] = {}

        unique_days = sorted(df["_date"].unique())

        # Diagnostic counters — returned in error message when no trades fire
        self._diag = {
            "data_source":    getattr(self, "_data_source", "unknown"),
            "total_bars":     len(df),
            "trading_days":   len(unique_days),
            "raw_signals":    0,   # bars where at least one strategy returned a Signal
            "below_floor":    0,   # signals filtered by 0.78 confidence floor
            "conflict_veto":  0,   # killed by conflict veto
            "direction_skip": 0,   # wrong direction (calls_only / puts_only)
            "no_contracts":   0,   # sized to 0 contracts
            "max_confidence": 0.0, # highest confidence seen (key: are we near the 0.78 floor?)
            "rvol_samples":   [],  # small sample of RVOL values for debugging
            "chop_bars":      0,   # bars where ADX<25 — gated strategies never evaluated at all
            "rr_gate_blocked": 0,  # passed every other gate but failed the R:R minimum (2026-07-22)
        }

        with _quiet_router_logging():
            for trade_date in unique_days:
                day_all = df[df["_date"] == trade_date].reset_index(drop=True)
                session_mask = (
                    (day_all["time"].dt.hour > 9) |
                    ((day_all["time"].dt.hour == 9) & (day_all["time"].dt.minute >= 30))
                ) & (day_all["time"].dt.hour < 16)
                day_df  = day_all[session_mask].reset_index(drop=True)
                day_str = trade_date.isoformat()

                # VWAP must stay precomputed on day_df — backtest_exit_sim.py's
                # exit engine reads bar["vwap"] every bar (vwap+trend-dead
                # check). This is exit-side, unrelated to the entry-detection
                # change above — do not remove.
                try:
                    _vb = compute_vwap_bands(day_df, num_stds=(1, 2))
                    day_df = day_df.copy()
                    day_df["vwap"]        = _vb["vwap"].ffill()
                    day_df["vwap_upper1"] = _vb["vwap_upper1"].ffill()
                    day_df["vwap_lower1"] = _vb["vwap_lower1"].ffill()
                    day_df["vwap_upper2"] = _vb["vwap_upper2"].ffill()
                    day_df["vwap_lower2"] = _vb["vwap_lower2"].ffill()
                except Exception:
                    pass

                pnl = self._simulate_day(day_df, balance, day_str)
                balance += pnl
                if pnl != 0:
                    daily_pnl[day_str] = pnl

        return self._compute_results(daily_pnl, balance)

    # ── Day simulation ────────────────────────────────────────────────────────

    def _simulate_day(
        self,
        day_df: pd.DataFrame,
        balance: float,
        day_str: str,
    ) -> float:
        """
        Simulate a single trading day.

        ENTRY (2026-07-21 rewrite): calls the REAL strategy_router.
        route_signals() — the exact function live trading uses — instead of
        a ~230-line hand-copied gate stack that had drifted from
        router_gates.py (e.g. it was missing the volume-ROC veto entirely).
        Ticks on 1-minute bars where Alpaca has coverage (matching live,
        which switched to 1-min scanning 2026-06-23), falling back to 5-min
        for older days. See diag_entry_resolution_comparison.py — the 1-min
        view caught a signal the 5-min view missed ENTIRELY on 8 of 17 SPY
        days (47%), which is why this exists.

        EXIT: UNCHANGED. Still the real risk.py engine via
        backtest_exit_sim.py, ticking on 5-min bars — deliberately not
        touched, to avoid risking the exit-fidelity fixes made earlier
        this session.
        """
        from strategies.base import _signal_cooldown
        _signal_cooldown.clear()

        if len(day_df) < 5:
            return 0.0

        ticker_iv  = _get_iv(self.ticker)
        trade_date = day_df["_date"].iloc[0]

        # ── Pick this day's entry-detection source (1-min preferred) ────────
        _src, _src_start, _src_res = None, None, "5min"
        if self._df1m is not None and trade_date in self._1m_day_start:
            _day1m_check = self._df1m[self._df1m["_date"] == trade_date]
            if len(_day1m_check) >= 25:
                _src, _src_start, _src_res = self._df1m, self._1m_day_start[trade_date], "1min"
        if _src is None:
            _src, _src_start, _src_res = self._df5m_full, self._5m_day_start.get(trade_date, 0), "5min"
        _day_ticks = _src[_src["_date"] == trade_date].reset_index(drop=True)
        _warmup    = 20 if _src_res == "1min" else 4

        # ── Bounded lookback floor for route_signals() (2026-07-22 speed fix) ──
        # Without this, bar_slice below grows from a few hundred rows to
        # 16,000+ over a 2-month backtest, and route_signals() re-scans all
        # of it every tick. Only compute_rvol()'s 10-day lookback needs
        # multi-day context (see ENTRY_LOOKBACK_DAYS comment) — cap it once
        # per day, not per tick.
        _day_start_map = self._1m_day_start if _src_res == "1min" else self._5m_day_start
        _all_days      = sorted(_day_start_map.keys())
        try:
            _day_pos = _all_days.index(trade_date)
        except ValueError:
            _day_pos = len(_all_days) - 1
        _floor_day_pos    = max(0, _day_pos - self.ENTRY_LOOKBACK_DAYS)
        _lookback_floor_idx = _day_start_map[_all_days[_floor_day_pos]]

        in_trade              = False
        entry_price           = 0.0
        entry_strike          = 0.0
        entry_bar_time: Optional[pd.Timestamp] = None
        option_type           = "call"
        contracts             = 0       # integer contract count (live bot units)
        remaining_contracts   = 0       # contracts left after stage 1 sell
        stage1_done           = False
        stage1_be_price: Optional[float] = None
        exit_state: Optional["ExitSimState"] = None
        session_pnl           = 0.0
        active_strategy       = "UNKNOWN"
        entry_date_str        = day_str
        # Captured at entry so post-hoc analysis can correlate win/loss with
        # what the signal actually looked like (RVOL, confidence, strategy-
        # specific meta like lh_depth_pct/bars_ago) — see diag_trend_cont_features.py
        active_confidence     = 0.0
        active_rvol           = 0.0
        active_meta: dict     = {}
        peak_opt_price        = 0.0

        idx_5m              = -1   # pointer into day_df (5-min) for exit management
        _last_exit_check_5m = -1   # avoid re-checking the same closed 5-min bar twice

        for i in range(_warmup, len(_day_ticks)):
            tick  = _day_ticks.iloc[i]
            ts    = tick["time"]
            close = float(tick["close"])

            # Advance the 5-min exit pointer to the latest bar CLOSED by now.
            # This is what lets a 1-min-driven outer loop still manage exits
            # on the unchanged 5-min exit engine below.
            while idx_5m + 1 < len(day_df) and day_df["time"].iloc[idx_5m + 1] <= ts:
                idx_5m += 1
            if idx_5m < 4:
                continue   # not enough 5-min history yet for the exit engine

            # ── Manage open position (exit engine — unchanged, 5-min cadence) ──
            if in_trade:
                if idx_5m == _last_exit_check_5m:
                    continue   # no new 5-min bar has closed since the last check
                _last_exit_check_5m = idx_5m

                bar = day_df.iloc[idx_5m]
                ts5 = bar["time"]
                elapsed_min = (ts5 - entry_bar_time).total_seconds() / 60

                # Reprice the same contract (fixed strike, _SIMULATED_DTE — was hardcoded 5, see fix above)
                opt_price = _estimate_option_price(
                    float(bar["close"]), entry_strike, _SIMULATED_DTE, iv=ticker_iv, option_type=option_type,
                )

                # ── Intrabar price simulation ─────────────────────────────────
                # Checking only the bar CLOSE misses what happened on the HIGH/LOW.
                # Conservative bar-path assumption: stops checked before targets.
                _bar_high_px = float(bar.get("high", bar["close"]))
                _bar_low_px  = float(bar.get("low",  bar["close"]))

                if option_type == "call":
                    _opt_bar_best  = _estimate_option_price(
                        _bar_high_px, entry_strike, _SIMULATED_DTE, iv=ticker_iv, option_type=option_type)
                    _opt_bar_worst = _estimate_option_price(
                        _bar_low_px,  entry_strike, _SIMULATED_DTE, iv=ticker_iv, option_type=option_type)
                else:  # put gains when underlying falls
                    _opt_bar_best  = _estimate_option_price(
                        _bar_low_px,  entry_strike, _SIMULATED_DTE, iv=ticker_iv, option_type=option_type)
                    _opt_bar_worst = _estimate_option_price(
                        _bar_high_px, entry_strike, _SIMULATED_DTE, iv=ticker_iv, option_type=option_type)

                # Track peak using the best intrabar price (not just close)
                if _opt_bar_best > peak_opt_price:
                    peak_opt_price = _opt_bar_best

                # ── Exit engine — real risk.py logic, OR the 3-rule simplified
                # variant under test (2026-07-22, see SIMPLIFIED_EXIT_MODE) ──
                if self.SIMPLIFIED_EXIT_MODE:
                    should_exit, exit_reason = evaluate_bt_exit_simplified(
                        exit_state, day_df, idx_5m,
                        current_opt_price = opt_price,
                    )
                else:
                    _bar_rvol = float(day_df.iloc[idx_5m].get("rvol", 0.0)) if "rvol" in day_df.columns else 0.0
                    should_exit, exit_reason = evaluate_bt_exit(
                        exit_state, day_df, idx_5m,
                        current_opt_price = opt_price,
                        opt_bar_best    = _opt_bar_best,
                        opt_bar_worst   = _opt_bar_worst,
                        stage1_done     = stage1_done,
                        stage1_be_price = stage1_be_price,
                        peak_opt_price  = peak_opt_price,
                        rvol            = _bar_rvol,
                        df_1h           = getattr(self, "_df_1h", None),
                        df_15m          = getattr(self, "_df_15m", None),
                    )

                if not should_exit:
                    continue   # still holding

                if exit_reason.startswith("stage1"):
                    # Sell 50%, arm the trailing stop on the remainder — same
                    # split as position_manager.py's live stage-1 handling.
                    s1_exit_px    = round(_opt_bar_best * (1.0 - self.SLIPPAGE_PCT), 4)
                    s1_contracts  = max(1, contracts // 2)
                    s1_pnl        = (s1_exit_px - entry_price) * s1_contracts * 100
                    session_pnl  += s1_pnl
                    self.trades.append({
                        "strategy_id":   active_strategy,
                        "option_type":   option_type,
                        "direction":     "long" if option_type == "call" else "short",
                        "entry_price":   entry_price,
                        "exit_price":    s1_exit_px,
                        "contracts":     s1_contracts,
                        "pnl":           round(s1_pnl, 2),
                        "exit_reason":   exit_reason.split(" ")[0],
                        "entry_hour":    entry_bar_time.hour,
                        "held_minutes":  round(elapsed_min, 1),
                        "date":          entry_date_str,
                        "entry_confidence": active_confidence,
                        "entry_rvol":        active_rvol,
                        "entry_meta":        active_meta,
                    })
                    remaining_contracts = contracts - s1_contracts
                    stage1_done         = True
                    stage1_be_price     = round(entry_price * (1.0 + STAGE2_TRAIL_PCT), 4)
                    continue

                # Any other reason is a full close. Stop-type reasons (structural,
                # ATR/swing trail, hard-stop fallback, VWAP+trend-dead, stage2
                # floor, momentum-death, early-momentum) fill at the bar's worst
                # price — they're adverse-move triggers. Time caps fill at the
                # bar's close (opt_price), matching the pre-fix convention.
                _adverse_reasons = (
                    "structural_stop", "atr_trail_stop", "initial_atr_stop",
                    "hard_stop", "vwap_trend_dead", "stage2_trail_stop",
                    "momentum_dead", "early_momentum_stop",
                    # 2026-07-22: the simplified 3-rule exit's stop-type reasons
                    # need the same worst-price fill convention as their
                    # equivalents above — only the time cap fills at close.
                    "simplified_hard_stop", "simplified_chandelier_3atr",
                )
                _fill_px = _opt_bar_worst if exit_reason.startswith(_adverse_reasons) else opt_price
                exit_px  = round(_fill_px * (1.0 - self.SLIPPAGE_PCT), 4)
                pnl = self._close_bt_trade(
                    entry_price, exit_px, remaining_contracts, option_type,
                    exit_reason, ts5.hour, round(elapsed_min, 1),
                    active_strategy, entry_date_str,
                    active_confidence, active_rvol, active_meta,
                )
                session_pnl += pnl
                in_trade = False
                continue

            # ── Signal detection — real route_signals(), same pipeline live uses ──
            _wgm = ts.hour * 60 + ts.minute
            _bt_windows = _get_trading_windows(balance)
            _in_window = any(
                int(s.split(":")[0]) * 60 + int(s.split(":")[1]) <= _wgm <=
                int(e.split(":")[0]) * 60 + int(e.split(":")[1])
                for s, e in _bt_windows
            )
            if not _in_window:
                continue

            # Multi-day slice up to now (not just today) — required for real
            # 10-day RVOL, matching what live actually feeds route_signals().
            # Bounded to the trailing ENTRY_LOOKBACK_DAYS (2026-07-22 speed
            # fix) instead of unbounded since day 1 — see _lookback_floor_idx
            # above for why this doesn't change RVOL fidelity.
            _global_idx = _src_start + i
            bar_slice   = _src.iloc[_lookback_floor_idx : _global_idx + 1]

            try:
                signals = route_signals(bar_slice, self.ticker, quiet=True)
            except Exception as _rs_ex:
                logger.debug("BT route_signals raised on %s bar %s: %s", self.ticker, ts, _rs_ex)
                continue

            if not signals:
                continue

            self._diag["raw_signals"] += 1
            if signals[0].confidence > self._diag["max_confidence"]:
                self._diag["max_confidence"] = round(signals[0].confidence, 4)
            _bar_rvol_diag = float(tick.get("rvol", 0) or 0) if "rvol" in _day_ticks.columns else 0.0
            if len(self._diag["rvol_samples"]) < 20 and _bar_rvol_diag > 0:
                self._diag["rvol_samples"].append(round(_bar_rvol_diag, 2))

            signal    = signals[0]
            direction = signal.direction
            strat_id  = signal.strategy_id
            _entry_confidence = signal.confidence
            _entry_rvol       = signal.rvol
            _entry_meta       = dict(signal.meta or {})

            # Direction filter (backtester-only override — calls_only/puts_only)
            opt_type_str = "call" if direction == "bullish" else "put"
            if self.direction == "calls_only" and opt_type_str != "call":
                self._diag["direction_skip"] += 1
                continue
            if self.direction == "puts_only"  and opt_type_str != "put":
                self._diag["direction_skip"] += 1
                continue

            # ── Simulate entry ────────────────────────────────────────────────
            strike      = _simulated_strike(close, direction)
            raw_opt_px  = _estimate_option_price(
                close, strike, _SIMULATED_DTE, iv=ticker_iv, option_type=opt_type_str,
            )
            if raw_opt_px <= 0.0:
                continue

            # Apply entry slippage (pay 5% more than quoted ask)
            entry_opt_px = round(raw_opt_px * (1.0 + self.SLIPPAGE_PCT), 4)
            if entry_opt_px <= 0.0:
                continue

            # ── Contract sizing — same 4-tier risk ladder as live bot ─────────
            n_contracts = self._size_contracts(balance, entry_opt_px)
            if n_contracts <= 0:
                self._diag["no_contracts"] += 1
                continue   # can't afford even 1 contract

            # ── R:R gate (2026-07-22 fidelity fix) ────────────────────────────
            # Live's trading/entry.py has ALWAYS called risk.evaluate_rr() and
            # blocked any entry below the 1.2x-1.6x minimum reward:risk before
            # this — the backtester never did. Every backtest run before today
            # included trades live would have refused to take. Wired in here so
            # backtest and live enforce the identical gate. Toggleable
            # (self.RR_GATE_ENABLED) so ab_test_rr_gate.py can compare against
            # the old ungated behavior and different threshold values.
            if self.RR_GATE_ENABLED:
                _rr_allowed, _rr_audit = self._risk.evaluate_rr(
                    entry_price=entry_opt_px, n_contracts=n_contracts,
                    entry_volume_multiplier=_entry_rvol,
                )
                if not _rr_allowed:
                    self._diag["rr_gate_blocked"] = self._diag.get("rr_gate_blocked", 0) + 1
                    continue

            in_trade             = True
            entry_price          = entry_opt_px
            entry_strike         = strike
            option_type          = opt_type_str
            entry_bar_time       = ts
            contracts            = n_contracts
            remaining_contracts  = n_contracts
            stage1_done          = False
            active_strategy      = strat_id
            entry_date_str       = day_str
            active_confidence    = _entry_confidence
            active_rvol          = _entry_rvol
            active_meta          = _entry_meta
            peak_opt_price       = entry_opt_px   # tracks highest option price for profit lock
            _last_exit_check_5m  = idx_5m         # don't re-check exit on the bar we just entered on

            # ── Structural stop + exit-sim state (real risk.py exit engine) ────
            # Same source as live's trading/entry.py: only signals whose meta
            # carries entry_bar_high (PUT) / entry_bar_low (CALL) get a
            # structural stop; everything else falls back to the initial ATR
            # stop / trail once one arms. See backtest_exit_sim.py.
            _entry_bar_level = active_meta.get("entry_bar_high") or active_meta.get("entry_bar_low")
            _struct_stop_opt = None
            if _entry_bar_level is not None:
                try:
                    _struct_stop_opt = self._risk.structural_stop_from_level(
                        entry_opt_px, close, float(_entry_bar_level))
                except Exception:
                    _struct_stop_opt = None
            _atr_at_entry = float(tick["atr"]) if "atr" in _day_ticks.columns and pd.notna(tick.get("atr")) else None
            exit_state = ExitSimState(
                direction         = direction,
                entry_price       = entry_opt_px,
                entry_bar_time    = ts,
                struct_stop_price = _struct_stop_opt,
                atr_at_entry      = _atr_at_entry,
            )

        # ── EOD: force-close any open position ───────────────────────────────
        if in_trade and remaining_contracts > 0:
            last_bar   = day_df.iloc[-1]
            last_close = float(last_bar["close"])
            eod_mid    = _estimate_option_price(
                last_close, entry_strike, _SIMULATED_DTE, iv=ticker_iv, option_type=option_type,
            )
            eod_price = round(eod_mid * (1.0 - self.SLIPPAGE_PCT), 4)
            eod_time  = last_bar["time"]
            elapsed   = (eod_time - entry_bar_time).total_seconds() / 60 if entry_bar_time else 0
            pnl = self._close_bt_trade(
                entry_price, eod_price, remaining_contracts, option_type,
                "eod", eod_time.hour if not isinstance(eod_time, float) else 15,
                round(elapsed, 1), active_strategy, entry_date_str,
                active_confidence, active_rvol, active_meta,
            )
            session_pnl += pnl

        return session_pnl

    # ── Trade recorder ────────────────────────────────────────────────────────

    def _close_bt_trade(
        self,
        entry_price: float,
        exit_price: float,
        n_contracts: int,
        option_type: str,
        reason: str,
        entry_hour: int = 10,
        held_minutes: float = 0.0,
        strategy_id: str = "UNKNOWN",
        date: str = "",
        confidence: float = 0.0,
        rvol: float = 0.0,
        meta: Optional[dict] = None,
    ) -> float:
        """
        Record a simulated trade and return its P&L.

        P&L uses real contract math: (exit - entry) × contracts × 100
        This is what the live bot computes in database.close_trade().

        confidence/rvol/meta (added 2026-07-17) capture what the ENTRY signal
        looked like — needed to find what actually distinguishes winning
        trades from losing ones within a strategy, instead of guessing at a
        single confidence-threshold knob. See diag_trend_cont_features.py.
        """
        if entry_price <= 0.0 or n_contracts <= 0:
            return 0.0
        pnl = (exit_price - entry_price) * n_contracts * 100
        self.trades.append({
            "strategy_id":   strategy_id,
            "option_type":   option_type,
            "direction":     "long" if option_type == "call" else "short",
            "entry_price":   entry_price,
            "exit_price":    exit_price,
            "contracts":     n_contracts,
            "pnl":           round(pnl, 2),
            "exit_reason":   reason,
            "entry_hour":    entry_hour,
            "held_minutes":  held_minutes,
            "date":          date,
            "entry_confidence": confidence,
            "entry_rvol":        rvol,
            "entry_meta":        meta or {},
        })
        return pnl

    # ── Results aggregation ───────────────────────────────────────────────────

    def _compute_results(self, daily_pnl: dict, final_balance: float) -> dict:
        """Aggregate backtest trades into summary statistics."""
        trades = self.trades
        pnls   = [t["pnl"] for t in trades]

        if not pnls:
            diag = getattr(self, "_diag", {})
            _rvol_str = str(diag.get("rvol_samples", [])[:10])
            return {
                "error": (
                    f"No trades generated. "
                    f"Bars={diag.get('total_bars',0)} "
                    f"Days={diag.get('trading_days',0)} "
                    f"RawSignalBars={diag.get('raw_signals',0)} "
                    f"BelowFloor={diag.get('below_floor',0)} "
                    f"ConflictVeto={diag.get('conflict_veto',0)} "
                    f"DirSkip={diag.get('direction_skip',0)} "
                    f"NoContracts={diag.get('no_contracts',0)} "
                    f"MaxConf={diag.get('max_confidence',0.0):.4f} "
                    f"RVOLsamples={_rvol_str}"
                )
            }

        wins   = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]

        # Per-strategy breakdown
        strategy_stats: dict[str, dict] = {}
        for t in trades:
            sid = t.get("strategy_id", "UNKNOWN")
            if sid not in strategy_stats:
                strategy_stats[sid] = {"trades": 0, "wins": 0, "pnl": 0.0}
            strategy_stats[sid]["trades"] += 1
            strategy_stats[sid]["pnl"]    += t["pnl"]
            if t["pnl"] > 0:
                strategy_stats[sid]["wins"] += 1

        strategy_breakdown = {}
        for sid, s in strategy_stats.items():
            wr = s["wins"] / s["trades"] * 100 if s["trades"] > 0 else 0.0
            strategy_breakdown[sid] = {
                "trades":   s["trades"],
                "wins":     s["wins"],
                "win_rate": round(wr, 1),
                "pnl":      round(s["pnl"], 2),
            }

        # Call vs Put breakdown
        calls     = [t for t in trades if t.get("option_type") == "call"]
        puts      = [t for t in trades if t.get("option_type") == "put"]
        call_wins = [t for t in calls if t["pnl"] > 0]
        put_wins  = [t for t in puts  if t["pnl"] > 0]

        # Exit reason breakdown
        exit_reasons: dict = {}
        for t in trades:
            r = t.get("exit_reason", "unknown")
            if r not in exit_reasons:
                exit_reasons[r] = {"count": 0, "pnl": 0.0}
            exit_reasons[r]["count"] += 1
            exit_reasons[r]["pnl"]   += t["pnl"]

        # Hold time
        held_times = [t.get("held_minutes", 0) for t in trades if t.get("held_minutes", 0) > 0]
        avg_hold   = round(sum(held_times) / len(held_times), 1) if held_times else 0.0

        # Stage-1 hit rate — prefix match now that stage1 has 4 possible
        # sub-reasons (2026-07-21) instead of the one flat-% string.
        stage1_exits = [t for t in trades if str(t.get("exit_reason", "")).startswith("stage1")]
        stage1_rate  = len(stage1_exits) / max(len(trades), 1) * 100

        # Avg contracts per trade
        avg_contracts = round(
            sum(t.get("contracts", 1) for t in trades) / max(len(trades), 1), 1
        )

        # Max consecutive losses
        max_consec, cur_consec = 0, 0
        for p in pnls:
            if p <= 0:
                cur_consec += 1
                max_consec  = max(max_consec, cur_consec)
            else:
                cur_consec = 0

        # Core stats
        win_rate   = len(wins) / len(pnls) if pnls else 0
        avg_win    = sum(wins)   / len(wins)   if wins   else 0
        avg_loss   = sum(losses) / len(losses) if losses else 0
        expectancy = (win_rate * avg_win) + ((1 - win_rate) * avg_loss)

        # Sharpe (annualised)
        daily_returns = list(daily_pnl.values())
        if len(daily_returns) > 1 and np.std(daily_returns) > 0:
            sharpe = (np.mean(daily_returns) / np.std(daily_returns)) * math.sqrt(252)
        else:
            sharpe = 0.0

        # Max drawdown
        equity, peak, max_dd = self.capital, self.capital, 0.0
        for p in pnls:
            equity += p
            if equity > peak:
                peak = equity
            dd = peak - equity
            if dd > max_dd:
                max_dd = dd

        return {
            "ticker":           self.ticker,
            "months":           self.months,
            "risk_pct_used":    self.risk_pct_override,   # None = tier ladder
            "avg_contracts":    avg_contracts,
            "total_trades":     len(pnls),
            "win_rate":         win_rate,
            "avg_win":          avg_win,
            "avg_loss":         avg_loss,
            "total_pnl":        sum(pnls),
            "final_balance":    final_balance,
            "total_return":     (final_balance - self.capital) / self.capital * 100,
            "max_drawdown":     max_dd,
            "sharpe_ratio":     round(sharpe, 2),
            "expectancy":       round(expectancy, 2),
            "max_consec_loss":  max_consec,
            "stage1_hit_rate":  round(stage1_rate, 1),
            "avg_hold_minutes": avg_hold,
            # Call vs Put
            "call_trades":      len(calls),
            "put_trades":       len(puts),
            "call_win_rate":    round(len(call_wins) / max(len(calls), 1) * 100, 1),
            "put_win_rate":     round(len(put_wins)  / max(len(puts),  1) * 100, 1),
            "call_pnl":         round(sum(t["pnl"] for t in calls), 2),
            "put_pnl":          round(sum(t["pnl"] for t in puts),  2),
            # Per-strategy breakdown
            "strategy_breakdown": strategy_breakdown,
            # Time / exit analysis
            "exit_reasons":     exit_reasons,
            "daily_pnl":        daily_pnl,
            "trades":           trades,
            # 2026-07-21: previously only surfaced in the zero-trades error
            # message. Always include it so a low (but nonzero) trade count
            # can be explained by real gate-by-gate numbers instead of
            # guessing — see run_full_audit.py's funnel summary.
            "diagnostics":      getattr(self, "_diag", {}),
        }
