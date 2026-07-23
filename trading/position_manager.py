"""
trading/position_manager.py — Adaptive position management with structure-aware exits.

REFACTOR (2026-06-26):
  Replaced the old 45-minute time-box exit with an adaptive state machine that
  exits on MARKET STRUCTURE events, not a countdown clock.

Exit hierarchy (checked in order each tick):
  1. Hard structural stop  — entry_bar_high/low-derived option stop (always on)
  2. ATR / swing trailing stop — tighter of (peak − 1.5×ATR) or last swing low/high
  3. VWAP breach + trend breakdown — only exits when ADX<20 OR EMA stack is misaligned
     (not on every dip below VWAP)
  4. Stage-1 profit target — +50% option gain → sell 50%, arm trailing stop
  5. Stage-2 trail floor  — remainder stops at entry×1.15 (locked-profit floor)
  6. Hard stop safety net — 20% below entry (tightens from 30 to 20%)
  7. Time cap of last resort — 90 min for winners, config.EARLY_TIMEBOX_MIN
     (currently 60 min) for flat/losing (safety net only; structure-based
     exits should fire first). NOTE 2026-07-18: this used to say "20 min" —
     stale; the live value is set in config.py, not here, so it won't drift
     out of sync with this comment again.

Per-position state machine keys (stored in this user's state["positions"][trade_id],
see trading/state.py::get_user_state):
  stage             : "s1" | "s2"
  phase             : "trending" | "vwap_watch" | "exit_pending"
  peak_price_opt    : highest option mid-price seen since entry
  peak_price_under  : highest (or lowest for puts) underlying close since entry
  atr_trail_stop    : current ATR/swing option-space trailing stop
  vwap_breached_at  : timestamp when VWAP breach first detected (or None)
  struct_stop_price : entry_bar_high/low-derived option stop (set at entry)
  stage1_done       : bool — True once 50% partial exit has been executed
  stage1_be_price   : trail floor option price locked after stage1 fires
"""

from __future__ import annotations

import logging
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd
import numpy as np

from trading.state import (
    get_user_state, get_user_risk, get_user_trade_log, set_user_trade_log,
    _now_et, _ET_TZ,
)
from config import get_bot_state_path
# RSI / MACD / ADX / EMA-stack / 1h-trend-bias — moved to trading/mtf_features.py
# (2026-07-18) so the entry path can share the exact same functions instead of
# a second, potentially-drifting copy. See that module's docstring for why.
from trading.mtf_features import (
    compute_adx, ema_stack_aligned, compute_rsi, compute_macd_hist, trend_bias_1h,
)

logger = logging.getLogger("celo_trader.trading_logic")


def _snapshot_exit_annotations(ticker: str) -> Optional[str]:
    """
    Thin, defensive wrapper around trading.annotations.snapshot_annotations()
    for every close_trade() call site in this file. Captures the bot's own
    chart annotations (BOS levels, exit markers, etc.) at the moment of exit
    so Journal replay can show why the trade closed, not just that it did —
    see database.py::close_trade()'s annotations_json merge for how this
    combines with whatever was already saved at entry.

    Never raises: a failed snapshot must never block closing a live trade.
    """
    if not ticker:
        return None
    try:
        from trading.annotations import snapshot_annotations  # noqa: PLC0415
        return snapshot_annotations(ticker)
    except Exception:
        logger.warning("Exit annotation snapshot failed for %s — trade will close with no new annotations", ticker, exc_info=True)
        return None


def _reconcile_if_phantom(alpaca: "AlpacaClient", trade: dict) -> bool:
    """
    Call right after an exit order comes back None (fill is None). If the
    rejection was Alpaca's specific "no matching position" signature, this
    trade was never actually opened at the broker — a fabricated/never-filled
    entry — and retrying the close will NEVER succeed no matter how many
    times we try. Auto-closes the DB row at $0 P&L instead of looping
    forever. Returns True if it reconciled (caller should stop, not fall
    through to the normal "stays open, will retry" path).

    FIX 2026-07-17: built after trade #163 (INTC $120 call, entered by the
    now-fixed paper-fill-fabrication bug) retried its exit every ~1s for
    hours straight, hammering Alpaca with a doomed sell_to_close order.
    """
    _US = get_user_state()
    from broker import is_phantom_position_rejection
    if not is_phantom_position_rejection(getattr(alpaca, "last_rejection_reason", None)):
        return False

    from database import close_trade, log_event, get_open_trades

    entry_px = trade.get("entry_price", 0) or 0
    close_trade(
        trade_id             = trade["id"],
        exit_price            = entry_px,
        exit_time             = _now_et(),
        exit_reason           = "auto_reconciled_no_broker_position",
        confirmed_fill_price  = entry_px,
        paper                 = trade.get("paper", True),
        annotations_json      = _snapshot_exit_annotations(trade.get("ticker", "")),
    )
    log_event(
        "ERROR", "trading_logic",
        f"🔧 [{trade.get('ticker', '?')}] {trade['contract_symbol']} — Alpaca has "
        f"no matching position for this trade, meaning the entry never actually "
        f"filled there. Auto-closed at $0 P&L instead of retrying forever. "
        f"Check Alpaca's Positions/Orders tabs if you want to verify.",
    )
    logger.error(
        "phantom_position_auto_reconciled",
        extra={
            "event": "phantom_position_auto_reconciled",
            "trade_id": trade["id"],
            "symbol": trade["contract_symbol"],
        },
    )
    _US["open_trades"] = get_open_trades()
    _US["open_trade"]  = _US["open_trades"][0] if _US["open_trades"] else None
    _US.get("positions", {}).pop(trade["id"], None)
    return True


# ── ATR / swing trailing stop constants ──────────────────────────────────────
_ATR_TRAIL_MULTIPLIER = 2.0   # baseline ATR trail multiplier (dynamically adjusted below)
_DELTA_APPROX         = 0.40  # approximate option delta for underlying→option conversion
_SWING_LOOKBACK       = 20    # bars to look back for swing high/low

# ── VWAP breach + trend breakdown constants ───────────────────────────────────
_ADX_WEAK_THRESHOLD   = 20    # ADX < 20 → trend has no directional strength
# _EMA_FAST/_EMA_MID/_EMA_SLOW moved to trading/mtf_features.py (only used by
# ema_stack_aligned, which now lives there too).
_VWAP_BREACH_BARS     = 5     # 1-min VWAP breach bars (fallback if 5-min unavailable)
_VWAP_5M_BREACH_BARS  = 2     # 5-min VWAP breach bars (cleaner structural signal)

# ── Time cap of last resort (safety net only) ─────────────────────────────────
_TIME_CAP_WINNER_MIN  = 90    # stage1 done  → 90 min max
_TIME_CAP_LOSER_MIN   = 20    # flat/losing  → 20 min max

# ── ATR trail warmup ──────────────────────────────────────────────────────────
_MIN_TRAIL_WARMUP_MIN = 5     # don't arm trail until 5 min into trade

# ── Multi-timeframe exit tuning ───────────────────────────────────────────────
# ATR trail multiplier is dynamically adjusted based on multi-TF context.
# Higher = more room for runners; lower = tighter, exits sooner.
_TRAIL_MULT_1H_WITH    = 2.5  # 1-hour trend aligned with trade → give runners room
_TRAIL_MULT_BASE       = 2.0  # default when 1-hour is neutral
_TRAIL_MULT_1H_AGAINST = 1.5  # 1-hour trend opposing trade → tighter stop
_TRAIL_MULT_TIGHT      = 1.0  # RSI exhaustion OR near 15-min swing level → very tight

_RSI_EXHAUST_CALL      = 72   # 5-min RSI above this while long = momentum exhaustion
_RSI_EXHAUST_PUT       = 28   # 5-min RSI below this while short = momentum exhaustion
_MACD_FADE_BARS        = 2    # MACD histogram declining for N consecutive 5-min bars
_15M_SWING_PROX_PCT    = 0.003  # within 0.3% of 15-min swing level = near resistance/support


# ── Indicator helpers ─────────────────────────────────────────────────────────
# NOTE: compute_adx / ema_stack_aligned / compute_rsi / compute_macd_hist /
# trend_bias_1h used to be defined here as module-private functions. They now
# live in trading/mtf_features.py (imported above) — this file only keeps the
# indicator helpers that are specific to the ATR/swing trailing-stop math.

def _compute_atr(df: pd.DataFrame, period: int = 14) -> Optional[float]:
    """14-bar ATR on 1-min underlying bars."""
    try:
        if len(df) < period + 1:
            return None
        hl  = df["high"]  - df["low"]
        hpc = (df["high"]  - df["close"].shift(1)).abs()
        lpc = (df["low"]   - df["close"].shift(1)).abs()
        tr  = pd.concat([hl, hpc, lpc], axis=1).max(axis=1)
        atr = float(tr.ewm(span=period, adjust=False).mean().iloc[-1])
        return atr if atr > 0 else None
    except Exception:
        return None


def _compute_vwap(df: pd.DataFrame) -> Optional[float]:
    """Session VWAP from 1-min bars (cumulative typical price × volume)."""
    try:
        if df.empty:
            return None
        tp  = (df["high"] + df["low"] + df["close"]) / 3.0
        cum_tpv = (tp * df["volume"]).cumsum()
        cum_vol = df["volume"].cumsum()
        vwap_series = cum_tpv / cum_vol.replace(0, np.nan)
        val = float(vwap_series.iloc[-1])
        return val if not np.isnan(val) else None
    except Exception:
        return None


def _structural_swing_stop(df: pd.DataFrame, direction: str, lookback: int = _SWING_LOOKBACK) -> Optional[float]:
    """
    Most recent confirmed swing low (for calls) or swing high (for puts)
    on the underlying, looked back `lookback` bars from the current bar.
    Uses a 3-bar pivot: bar whose low < both neighbors (or high > both neighbors).
    """
    try:
        if len(df) < lookback + 2:
            return None
        window = df.iloc[-lookback:].reset_index(drop=True)
        pivots = []
        for i in range(1, len(window) - 1):
            if direction == "bullish":
                if window.iloc[i]["low"] < window.iloc[i-1]["low"] and \
                   window.iloc[i]["low"] < window.iloc[i+1]["low"]:
                    pivots.append(float(window.iloc[i]["low"]))
            else:
                if window.iloc[i]["high"] > window.iloc[i-1]["high"] and \
                   window.iloc[i]["high"] > window.iloc[i+1]["high"]:
                    pivots.append(float(window.iloc[i]["high"]))
        return pivots[-1] if pivots else None
    except Exception:
        return None


def _underlying_stop_to_option(
    entry_option: float,
    underlying_current: float,
    underlying_stop: float,
) -> float:
    """
    Convert an underlying stop level to an option stop price using delta.
    Option stop = entry_option − |move| × DELTA_APPROX
    Floored at 20% below entry (hard safety net).
    """
    move         = abs(underlying_current - underlying_stop)
    option_stop  = entry_option - move * _DELTA_APPROX
    hard_floor   = entry_option * 0.80  # 20% hard floor
    return round(max(option_stop, hard_floor, 0.01), 4)


# ── Main position manager ─────────────────────────────────────────────────────

def _manage_open_position(
    alpaca: "AlpacaClient",
    tradier: "TradierClient",
    trade: dict,
    balance: float,
) -> None:
    """
    Adaptive position manager — structure-driven exits, not time-driven.

    Called every tick for each open trade. Fetches both an option quote (for
    current P&L) and the underlying's 1-min bars (for structural analysis).
    All exit decisions are made against chart structure, not a clock.
    """
    # FIX: previously read the RiskManager/trade-logger off `trading.entry`'s
    # module-level globals via `_risk`/`_trade_log` — shared by every
    # user's thread. Now resolved fresh per user (see trading/state.py).
    _US        = get_user_state()
    _risk      = get_user_risk()
    _trade_log = get_user_trade_log()

    try:
        # ── Option quote ──────────────────────────────────────────────────────
        quote = tradier.get_option_quote(trade["contract_symbol"])
        if quote is None:
            logger.warning("Cannot price %s — holding", trade["contract_symbol"])
            return

        current_price = quote["mid"]
        bid_price     = float(quote.get("bid") or quote["mid"])  # for limit sell step-down
        entry_price   = trade["entry_price"]
        trade_id      = trade["id"]
        ticker        = trade.get("ticker", "")
        option_type   = (trade.get("option_type") or "call").lower()
        direction     = "bullish" if option_type == "call" else "bearish"

        # ── Per-position state ────────────────────────────────────────────────
        ps = _US["positions"].setdefault(trade_id, {
            "peak_price":                None,   # MFE: highest option price seen
            "min_price":                 None,   # MAE: lowest  option price seen (adverse)
            "entry_time":                trade.get("entry_time"),
            "stage1_done":               False,
            "stage1_be_price":           None,
            "current_stop_pct":          _risk.ORB_STOP_PCT if _risk else 0.20,
            "struct_stop_price":         None,
            "current_option_price":      None,
            "current_option_price_time": None,
            "last_position_narration_minute": None,
            # Adaptive state machine
            "atr_trail_stop":            None,
            "initial_atr_stop":          None,   # ATR-based stop set on first tick; replaces fixed 20% hard stop
            "vwap_breached_bars":        0,     # consecutive 1-min bars below/above VWAP (fallback)
            "vwap_5m_breached_bars":     0,     # consecutive 5-min bars below/above VWAP (primary)
            "peak_underlying":           None,  # highest underlying close for trail calc
            "last_bar_fetch_minute":     None,  # throttle: 1-min bars — fetch max once/minute
            "cached_underlying_df":      None,  # 1-min bar cache
            # Multi-timeframe caches (throttled by bar boundary)
            "cached_5m_df":              None,
            "cached_15m_df":             None,
            "cached_1h_df":              None,
            "last_5m_fetch_key":         None,  # "%Y-%m-%d %H:MM//5" bar key
            "last_15m_fetch_key":        None,  # "%Y-%m-%d %H:MM//15" bar key
            "last_1h_fetch_key":         None,  # "%Y-%m-%d %H" bar key
        })

        ps["current_option_price"]      = current_price
        ps["current_option_price_time"] = _now_et().strftime("%H:%M:%S")

        # ── Entry time recovery ───────────────────────────────────────────────
        entry_time_iso = ps.get("entry_time") or trade.get("entry_time")
        try:
            entry_time = datetime.fromisoformat(entry_time_iso) if entry_time_iso else None
            if entry_time is not None and entry_time.tzinfo is None:
                entry_time = _ET_TZ.localize(entry_time)
        except Exception:
            entry_time = None

        # ── Peak option price tracking (MFE) ─────────────────────────────────
        from risk import persist_peak_price, recover_peak_price
        if ps.get("peak_price") is None:
            ps["peak_price"] = recover_peak_price(trade_id) or entry_price
        if current_price > ps["peak_price"]:
            ps["peak_price"] = current_price
            persist_peak_price(trade_id, current_price)

        # ── Minimum option price tracking (MAE) ───────────────────────────────
        # MAE = max adverse excursion: how far the option price fell below entry.
        # Initialise to entry_price so we only record genuine adverse moves.
        if ps.get("min_price") is None:
            ps["min_price"] = entry_price
        if current_price < ps["min_price"]:
            ps["min_price"] = current_price

        stage1_done     = bool(ps.get("stage1_done"))
        stage1_be_price = ps.get("stage1_be_price")
        now_et          = _now_et()

        # ── Fetch underlying bars (throttled to once per minute) ──────────────
        _minute_key = now_et.strftime("%Y-%m-%d %H:%M")
        df_under: Optional[pd.DataFrame] = ps.get("cached_underlying_df")

        if ps.get("last_bar_fetch_minute") != _minute_key:
            try:
                from signals import bars_to_df
                _bars, _err, _ = alpaca.get_session_bars(ticker, "1Min")
                if _bars and not _err:
                    df_under = bars_to_df(_bars)
                    ps["cached_underlying_df"] = df_under
                    ps["last_bar_fetch_minute"] = _minute_key

                    # Update peak underlying price
                    _last_close = float(df_under["close"].iloc[-1])
                    if direction == "bullish":
                        ps["peak_underlying"] = max(ps.get("peak_underlying") or _last_close, _last_close)
                    else:
                        # For puts: track the minimum underlying (we want price to fall)
                        ps["peak_underlying"] = min(ps.get("peak_underlying") or _last_close, _last_close)
            except Exception as _be:
                logger.debug("Bar fetch for position management failed (%s): %s", ticker, _be)

        # ── Fetch 5-min bars (throttled to once per 5-min bar) ───────────────
        # Used for: RSI exhaustion, MACD fade, 5-min VWAP breach, 5-min ATR
        _5m_bar_key = now_et.strftime("%Y-%m-%d %H:") + str(now_et.minute // 5)
        df_5m: Optional[pd.DataFrame] = ps.get("cached_5m_df")
        if ps.get("last_5m_fetch_key") != _5m_bar_key:
            try:
                from signals import bars_to_df as _btd
                _b5, _e5, _ = alpaca.get_session_bars(ticker, "5Min")
                if _b5 and not _e5:
                    df_5m = _btd(_b5)
                    ps["cached_5m_df"]      = df_5m
                    ps["last_5m_fetch_key"] = _5m_bar_key
            except Exception as _e5m:
                logger.debug("5m bar fetch failed (%s): %s", ticker, _e5m)

        # ── Fetch 15-min bars (throttled to once per 15-min bar) ─────────────
        # Used for: swing level proximity check
        _15m_bar_key = now_et.strftime("%Y-%m-%d %H:") + str(now_et.minute // 15)
        df_15m: Optional[pd.DataFrame] = ps.get("cached_15m_df")
        if ps.get("last_15m_fetch_key") != _15m_bar_key:
            try:
                from signals import bars_to_df as _btd
                _b15, _e15, _ = alpaca.get_session_bars(ticker, "15Min")
                if _b15 and not _e15:
                    df_15m = _btd(_b15)
                    ps["cached_15m_df"]      = df_15m
                    ps["last_15m_fetch_key"] = _15m_bar_key
            except Exception as _e15m:
                logger.debug("15m bar fetch failed (%s): %s", ticker, _e15m)

        # ── Fetch 1-hour bars (throttled to once per hour) ───────────────────
        # Used for: macro trend bias (EMA20 alignment)
        _1h_bar_key = now_et.strftime("%Y-%m-%d %H")
        df_1h: Optional[pd.DataFrame] = ps.get("cached_1h_df")
        if ps.get("last_1h_fetch_key") != _1h_bar_key:
            try:
                from signals import bars_to_df as _btd
                _b1h, _e1h = alpaca.get_bars(ticker, "1Hour", limit=100)
                if _b1h and not _e1h:
                    df_1h = _btd(_b1h)
                    ps["cached_1h_df"]      = df_1h
                    ps["last_1h_fetch_key"] = _1h_bar_key
            except Exception as _e1h:
                logger.debug("1h bar fetch failed (%s): %s", ticker, _e1h)

        # ── Compute adaptive trailing stop from bars ───────────────────────────
        atr_trail_stop: Optional[float]  = ps.get("atr_trail_stop")
        vwap: Optional[float]            = None
        trend_dead: bool                 = False
        _rvol_for_exit: float            = 0.0   # passed to momentum-death check in risk.py

        # Dynamic stage1 trigger inputs (2026-07-21) — populated below if
        # ATR/5m data is available; risk.py fails open to the flat % if not.
        _atr_target_price: Optional[float] = None
        _momentum_fading: bool             = False

        # Trade age in minutes — used to gate the ATR trail warmup
        _trade_age_min = (
            (now_et - entry_time).total_seconds() / 60
            if entry_time else 999.0
        )

        # ── Multi-timeframe exit signals → dynamic ATR trail multiplier ─────────
        # Each timeframe narrows or widens the ATR trail independently.
        # Signals stack: RSI exhaustion on top of a 1h headwind = very tight stop.
        _dynamic_trail_mult = _TRAIL_MULT_BASE   # start at 2.0×
        _mtf_notes: list[str] = []

        # 1-hour trend bias: gives runners more room when aligned, tightens when opposing
        _1h_bias = trend_bias_1h(df_1h, direction)
        if _1h_bias == "with":
            _dynamic_trail_mult = _TRAIL_MULT_1H_WITH   # 2.5×
            _mtf_notes.append(f"1h_trend=WITH({_TRAIL_MULT_1H_WITH}×)")
        elif _1h_bias == "against":
            _dynamic_trail_mult = min(_dynamic_trail_mult, _TRAIL_MULT_1H_AGAINST)  # 1.5×
            _mtf_notes.append(f"1h_trend=AGAINST({_TRAIL_MULT_1H_AGAINST}×)")

        if df_5m is not None and not df_5m.empty:
            # 5-min RSI exhaustion: caps trail very tight regardless of other signals
            _5m_rsi = compute_rsi(df_5m)
            _rsi_exhausted = (
                (_5m_rsi is not None and direction == "bullish" and _5m_rsi >= _RSI_EXHAUST_CALL) or
                (_5m_rsi is not None and direction == "bearish" and _5m_rsi <= _RSI_EXHAUST_PUT)
            )
            if _rsi_exhausted:
                _dynamic_trail_mult = min(_dynamic_trail_mult, _TRAIL_MULT_TIGHT)  # 1.0×
                _mtf_notes.append(f"5m_rsi_exhaust={_5m_rsi:.0f}({_TRAIL_MULT_TIGHT}×)")

            # 5-min MACD histogram declining for ≥ 2 bars = momentum fading
            _macd_hist = compute_macd_hist(df_5m)
            _macd_fading = len(_macd_hist) >= _MACD_FADE_BARS and all(
                _macd_hist[-(i + 1)] < _macd_hist[-(i + 2)]
                for i in range(_MACD_FADE_BARS - 1)
            )
            if _macd_fading:
                _dynamic_trail_mult = min(_dynamic_trail_mult, _TRAIL_MULT_1H_AGAINST)  # 1.5×
                _mtf_notes.append(f"5m_macd_fade({_TRAIL_MULT_1H_AGAINST}×)")

            # Reused for the dynamic stage1 trigger (risk.py) — same RSI/MACD
            # signals already computed above for the trail multiplier, not
            # recomputed a second time.
            # 2026-07-21: OR vs AND is now settings-driven (STAGE1_MOMENTUM_
            # REQUIRE_BOTH) — diagnosis found the OR combination let either
            # signal alone fire the stage1 exit at just +10% gain, never
            # letting the ATR target get a chance. AND is an untested
            # candidate, not yet the default — see ab_test_momentum_fade_tuning.py.
            _momentum_fading = (
                (_rsi_exhausted and _macd_fading) if (_risk and _risk.STAGE1_MOMENTUM_REQUIRE_BOTH)
                else (_rsi_exhausted or _macd_fading)
            )

            # 5-min VWAP breach tracking (cleaner signal than 1-min)
            _5m_vwap = _compute_vwap(df_5m)
            _5m_close = float(df_5m["close"].iloc[-1])
            if _5m_vwap is not None:
                _5m_breached = (
                    (direction == "bullish" and _5m_close < _5m_vwap) or
                    (direction == "bearish" and _5m_close > _5m_vwap)
                )
                if _5m_breached:
                    ps["vwap_5m_breached_bars"] = ps.get("vwap_5m_breached_bars", 0) + 1
                else:
                    ps["vwap_5m_breached_bars"] = 0

        if df_15m is not None and not df_15m.empty:
            # 15-min swing level proximity: if price is at a key level, get very tight
            _15m_close = float(df_15m["close"].iloc[-1])
            _swing_15m = _structural_swing_stop(df_15m, direction, lookback=20)
            if _swing_15m is not None and _15m_close > 0:
                _prox_pct = abs(_15m_close - _swing_15m) / _15m_close
                if _prox_pct <= _15M_SWING_PROX_PCT:
                    _dynamic_trail_mult = min(_dynamic_trail_mult, _TRAIL_MULT_TIGHT)  # 1.0×
                    _mtf_notes.append(f"near_15m_swing={_prox_pct*100:.2f}%({_TRAIL_MULT_TIGHT}×)")

        if _mtf_notes:
            logger.debug("[%s] MTF trail mult=%.1f× — %s", ticker, _dynamic_trail_mult, " | ".join(_mtf_notes))

        if df_under is not None and not df_under.empty:
            _underlying_now = float(df_under["close"].iloc[-1])

            # ATR-based trailing stop in underlying space.
            # Uses 5-min ATR when available (less noisy than 1-min), falls back to 1-min.
            _atr = _compute_atr(df_5m) if (df_5m is not None and len(df_5m) >= 15) else _compute_atr(df_under)

            # Dynamic stage1 target (2026-07-21): ATR-scaled, recomputed every
            # tick same as the trail — NOT frozen at entry, so it adapts as
            # volatility changes through the trade. risk.py fails open to the
            # flat % (ORB_STAGE1_GAIN) whenever this stays None (no ATR yet).
            if _atr is not None and _risk:
                _atr_target_price = entry_price + _risk.STAGE1_ATR_TARGET_MULT * _atr * _DELTA_APPROX

            # ── Initial ATR stop (computed once; replaces fixed 20% hard stop) ────
            # On the very first tick with ATR data, derive a stop based on how much
            # the underlying actually moves — not a fixed % of option premium.
            if _atr is not None and ps.get("initial_atr_stop") is None:
                _init_mult    = 2.5
                _atr_opt_stop = entry_price - _init_mult * _atr * _DELTA_APPROX
                ps["initial_atr_stop"] = round(
                    max(entry_price * 0.70, min(entry_price * 0.85, _atr_opt_stop)), 4
                )
                logger.info(
                    "[%s] Initial ATR stop set: ATR=%.4f × %.1f× → opt_stop=%.4f (final=%.4f, bounds=[%.4f, %.4f])",
                    ticker, _atr, _init_mult, _atr_opt_stop,
                    ps["initial_atr_stop"], entry_price * 0.70, entry_price * 0.85,
                )

            # PROFIT GATE: only arm the ATR trail once the option is at least
            # Trail arms only after +15% gain — before that it's stopped by noise.
            _opt_gain_pct = (current_price - entry_price) / entry_price if entry_price else 0.0
            _trail_profit_gate = _opt_gain_pct >= 0.15
            if (_atr is not None
                    and ps.get("peak_underlying") is not None
                    and _trade_age_min >= _MIN_TRAIL_WARMUP_MIN
                    and _trail_profit_gate):
                _peak_u = float(ps["peak_underlying"])
                if direction == "bullish":
                    _atr_stop_u = _peak_u - _dynamic_trail_mult * _atr
                else:
                    _atr_stop_u = _peak_u + _dynamic_trail_mult * _atr

                _atr_stop_opt = _underlying_stop_to_option(
                    entry_price, _underlying_now, _atr_stop_u
                )

                # Structural swing stop in underlying space
                _swing_u = _structural_swing_stop(df_under, direction)
                if _swing_u is not None:
                    _swing_opt = _underlying_stop_to_option(
                        entry_price, _underlying_now, _swing_u
                    )
                    # Use tighter of ATR trail and swing level
                    if direction == "bullish":
                        _new_trail = max(_atr_stop_opt, _swing_opt)
                    else:
                        _new_trail = max(_atr_stop_opt, _swing_opt)
                else:
                    _new_trail = _atr_stop_opt

                # Trail stop can only TIGHTEN (ratchet up), never loosen
                if atr_trail_stop is None or _new_trail > atr_trail_stop:
                    atr_trail_stop = _new_trail
                    ps["atr_trail_stop"] = atr_trail_stop

            # RVOL proxy for momentum-death exit check in risk.py.
            # 2026-07-15 audit: was current 1-min vol ÷ 20-bar mean — intraday volume
            try:
                if df_5m is not None and len(df_5m) >= 5:
                    _v5       = df_5m["volume"].astype(float)
                    _curr_vol = float(_v5.iloc[-1])
                    _base_vol = float(_v5.iloc[-5:-1].median())
                else:
                    _curr_vol = float(df_under["volume"].iloc[-1])
                    _base_vol = float(df_under["volume"].iloc[-20:].mean()) if len(df_under) >= 5 else _curr_vol
                _rvol_for_exit = _curr_vol / _base_vol if _base_vol > 0 else 0.0
            except Exception:
                _rvol_for_exit = 0.0

            # VWAP
            vwap = _compute_vwap(df_under)

            # VWAP breach tracking (consecutive bars below/above VWAP)
            if vwap is not None:
                _vwap_breached_now = (
                    (direction == "bullish" and _underlying_now < vwap) or
                    (direction == "bearish" and _underlying_now > vwap)
                )
                if _vwap_breached_now:
                    ps["vwap_breached_bars"] = ps.get("vwap_breached_bars", 0) + 1
                else:
                    ps["vwap_breached_bars"] = 0   # reset on any bar back through VWAP

            # Trend breakdown check — use 5-min VWAP breach when available
            # (2 consecutive 5-min bars is a stronger signal than 5 noisy 1-min bars),
            # falling back to 1-min counter if 5-min data hasn't loaded yet.
            _vwap_breached = (
                ps.get("vwap_5m_breached_bars", 0) >= _VWAP_5M_BREACH_BARS
                if df_5m is not None
                else ps.get("vwap_breached_bars", 0) >= _VWAP_BREACH_BARS
            )
            if _vwap_breached:
                # Prefer 5-min bars for ADX/EMA check (less noise than 1-min)
                _df_for_trend = df_5m if (df_5m is not None and len(df_5m) >= 55) else df_under
                _adx    = compute_adx(_df_for_trend)
                _ema_ok = ema_stack_aligned(_df_for_trend, direction)
                adx_weak   = (_adx is not None and _adx < _ADX_WEAK_THRESHOLD)
                ema_broken = not _ema_ok
                # Require BOTH conditions — ADX<20 alone is common during normal
                # mid-morning consolidation. Both together = confirmed dead.
                trend_dead = adx_weak and ema_broken

        # Persist current stop for dashboard visibility
        _current_stop_pct_display = (
            round(1.0 - atr_trail_stop / entry_price, 4) if atr_trail_stop else
            (_risk.ORB_STOP_PCT if _risk else 0.20)
        )
        ps["current_stop_pct"] = _current_stop_pct_display

        # ── Write to bot_state.json ───────────────────────────────────────────
        import json as _json_m
        _state_path_m = get_bot_state_path()
        try:
            _existing = {}
            if _state_path_m.exists():
                with open(_state_path_m) as _f:
                    _existing = _json_m.load(_f)
            _open_positions = _existing.get("open_positions") or {}
            _open_positions[str(trade_id)] = {
                "trade_id":                  trade_id,
                "contract_symbol":           trade.get("contract_symbol"),
                "ticker":                    ticker,
                "option_type":               option_type,
                "entry_price":               entry_price,
                "contracts":                 trade.get("contracts"),
                "current_stop_pct":          _current_stop_pct_display,
                "current_option_price":      current_price,
                "current_option_price_time": ps["current_option_price_time"],
                "stage1_done":               stage1_done,
                "peak_price":                ps["peak_price"],
                "min_price":                 ps.get("min_price"),  # MAE tracking
                "entry_time":                entry_time_iso,
                "atr_trail_stop":            atr_trail_stop,
                "initial_atr_stop":          ps.get("initial_atr_stop"),
                "vwap_breached_bars":        ps.get("vwap_breached_bars", 0),
                "trend_dead":                trend_dead,
            }
            _existing["open_positions"]             = _open_positions
            _existing["current_stop_pct"]           = _current_stop_pct_display
            _existing["current_option_price"]       = current_price
            _existing["current_option_price_time"]  = ps["current_option_price_time"]
            # Always carry the latest session_pnl so the WebSocket never reads a stale value
            _existing["session_pnl"]                = _US.get("session_pnl", 0.0)
            with open(_state_path_m, "w") as _f:
                _json_m.dump(_existing, _f)
        except Exception:
            pass

        _struct_stop = ps.get("struct_stop_price")

        # ── Per-minute narration ──────────────────────────────────────────────
        if ps.get("last_position_narration_minute") != _minute_key:
            from database import log_event
            ps["last_position_narration_minute"] = _minute_key
            _contracts  = trade.get("contracts", 1)
            _pnl_now    = (current_price - entry_price) * _contracts * 100
            _pnl_pct    = (current_price - entry_price) / entry_price * 100 if entry_price else 0.0
            _stop_desc  = f"${atr_trail_stop:.2f} (ATR/swing trail)" if atr_trail_stop else f"{_current_stop_pct_display*100:.0f}% below entry"
            _stage_desc = "Stage 2 — runner, trail active" if stage1_done else "Stage 1 — full size"
            _vwap_desc  = ""
            if ps.get("vwap_breached_bars", 0) >= _VWAP_BREACH_BARS:
                _vwap_desc = f" ⚠️ VWAP breach {ps['vwap_breached_bars']}bar — trend_dead={trend_dead}."
            log_event(
                "INFO", "position_update",
                f"🟡 [{trade['contract_symbol']}] Holding — "
                f"option @ ${current_price:.2f} (entry ${entry_price:.2f}, peak ${ps['peak_price']:.2f}). "
                f"P&L {'+' if _pnl_now >= 0 else ''}${_pnl_now:.2f} ({_pnl_pct:+.1f}%). "
                f"Stop {_stop_desc}. {_stage_desc}.{_vwap_desc}"
            )

        # ── Exit decision ─────────────────────────────────────────────────────
        # Build vwap_breached flag: any ≥1 bar breach (for profitable-exit rule)
        _vwap_breached_any = (
            ps.get("vwap_5m_breached_bars", 0) >= 1
            if df_5m is not None
            else ps.get("vwap_breached_bars", 0) >= 1
        )

        # Use the armed ATR trail if available; fall back to the initial ATR stop
        # Suppressed during warmup (first 5 min / before +15% gain).
        # FIX 2026-07-18: `atr_trail_stop` (the local var, armed trail from
        # ps["atr_trail_stop"]) and the initial-stop fallback used to be
        # merged into one value before reaching risk.py, which logged BOTH
        # cases as reason "atr_trail_stop" — mislabeling instant stop-outs
        # (the static initial stop firing in the first few minutes, before
        # the real trail can arm) as trailing-stop failures. Per
        # diag_instant_reversals.py's finding on 3 live trades that stopped
        # out in 0-2 min at 0% MFE. `_trail_is_armed` now tells risk.py which
        # case this actually is so the reason string can differ.
        _trail_is_armed     = atr_trail_stop is not None
        _effective_atr_stop = atr_trail_stop or ps.get("initial_atr_stop")

        # ── Exit decision: simplified 3-rule path OR the full 9+-condition
        # engine (2026-07-22, see trading/simplified_exit_live.py). Gated by
        # a settings toggle (default True) so it's a one-flip rollback, not
        # a one-way door — same reversibility every fix shipped with today.
        from config import get_settings as _gs_exit
        _simplified_mode = bool(_gs_exit().get("simplified_exit_mode", True))
        _atr_for_exit        = locals().get("_atr")
        _underlying_for_exit = locals().get("_underlying_now")
        if _simplified_mode and _atr_for_exit is not None and _underlying_for_exit is not None:
            from trading.simplified_exit_live import evaluate_simplified_live_exit
            should_exit, reason = evaluate_simplified_live_exit(
                ps, entry_price, current_price,
                entry_time=entry_time, now=now_et, direction=direction,
                atr=_atr_for_exit, underlying_now=_underlying_for_exit,
            )
        else:
            # Fail-open to the full engine if simplified mode is off, or if
            # bar data isn't ready yet for the chandelier calc — same
            # fail-open convention used throughout this file.
            should_exit, reason = _risk.should_exit(
                entry_price, current_price,
                entry_time      = entry_time,
                now             = now_et,
                stage1_done     = stage1_done,
                stage1_be_price = stage1_be_price,
                peak_price      = ps.get("peak_price"),   # MFE for giveback rule
                struct_stop_price = _struct_stop,
                atr_trail_stop  = _effective_atr_stop,    # initial or armed ATR stop
                trail_armed     = _trail_is_armed,        # which case the above actually is
                vwap            = vwap,
                vwap_breached   = _vwap_breached_any,     # any breach (≥1 bar)
                trend_dead      = trend_dead,
                direction       = direction,
                rvol            = _rvol_for_exit,
                atr_target_price = _atr_target_price,   # dynamic stage1 trigger (2026-07-21)
                momentum_fading  = _momentum_fading,
            )

        if not should_exit:
            return

        # NOTE: AI reasoning narration for this exit decision does NOT fire
        # here anymore. It used to fire right at this point (as soon as
        # should_exit()==True), which was a bug: if the close order below is
        # slow to fill, gets rejected, or is retried, should_exit() keeps
        # returning True on every following tick and this point gets
        # re-reached repeatedly for a position that never actually closed —
        # confirmed in production (2026-07-20/21): one trade generated 167
        # duplicate exit-narration calls over 20 minutes because its close
        # order never confirmed. narrate_exit() is now called ONLY after a
        # close_trade() call actually confirms — see _close_position() below
        # and the stage-1 partial-exit branch a few lines down — same
        # "narrate after confirmation, not after intent" pattern narrate_entry()
        # already used correctly in trading/entry.py.

        # ── Stage 1: sell 50%, arm trailing stop on remainder ────────────────
        if reason.startswith("stage1"):
            half_contracts = max(1, trade["contracts"] // 2)
            from database import log_event

            if half_contracts >= trade["contracts"]:
                log_event(
                    "INFO", "trading_logic",
                    f"🟢 [{trade['ticker']}] +50% target hit — only "
                    f"{trade['contracts']} contract(s) held, taking full exit "
                    f"(can't split a single contract). Closing now.",
                )
                # 2026-07-21: preserve the REAL trigger tag (ATR target /
                # momentum fade / volume fade / static fallback) instead of
                # a hardcoded generic label — same fix as backtester.py's
                # matching bug, needed now that stage1 has 4 possible
                # sub-reasons instead of one flat %.
                _close_position(alpaca, trade, current_price,
                                f"{reason.split(' ')[0]}_full_exit_single_contract",
                                bid_price=bid_price, mtf_notes=_mtf_notes)
                return

            from config import get_settings
            settings = get_settings()
            paper    = settings.get("paper_trading", True)

            if paper:
                _trade_log.info(
                    "stage1_partial_exit",
                    extra={
                        "event":          "stage1_partial_exit",
                        "contracts_sold": half_contracts,
                        "exit_price":     round(current_price, 4),
                        "entry_price":    round(entry_price, 4),
                    },
                )
            # Limit sell at mid; live steps down to bid after 5s if not taken.
            fill = alpaca.place_option_order(
                symbol          = trade["contract_symbol"],
                qty             = half_contracts,
                side            = "sell",
                order_type      = "limit",
                limit_price     = current_price,   # mid price
                step_to_price   = bid_price,        # step down to bid on live
                position_intent = "sell_to_close",
            )

            if fill is None:
                if _reconcile_if_phantom(alpaca, trade):
                    return
                log_event(
                    "WARNING", "trading_logic",
                    f"🟡 [{trade['contract_symbol']}] Stage-1 profit-take order "
                    f"did not fill — leaving at full size, will retry next tick.",
                )
                return

            fill_price = float(fill.get("confirmed_fill_price") or fill.get("filled_avg_price") or current_price)

            # FIX 2026-07-20 (Alpaca fills audit): broker.py may now return a
            # PARTIAL fill result (fewer contracts than requested) instead of
            # either None or a full fill. Use the REAL filled_qty here so the
            # synthetic "sold" row and the parent's remaining-contracts count
            # both match what Alpaca actually did — previously this always
            # assumed exactly half_contracts sold, which would silently
            # overstate the sale and understate the remaining open size.
            _sold_qty = int(fill.get("filled_qty") or half_contracts)
            if _sold_qty > half_contracts:
                _sold_qty = half_contracts  # defensive clamp, should never exceed request
            if _sold_qty != half_contracts:
                log_event(
                    "WARNING", "trading_logic",
                    f"🟡 [{trade['contract_symbol']}] Stage-1 profit-take only sold "
                    f"{_sold_qty} of {half_contracts} intended contract(s) — "
                    f"recording the REAL sold size.",
                )
                logger.warning(
                    "partial_fill_stage1: trade_id=%s requested=%d filled=%d",
                    trade["id"], half_contracts, _sold_qty,
                )
            if _sold_qty < 1:
                log_event(
                    "WARNING", "trading_logic",
                    f"🟡 [{trade['contract_symbol']}] Stage-1 profit-take reported "
                    f"filled but 0 contracts actually sold — leaving position at "
                    f"full size, will retry next tick.",
                )
                return

            from database import insert_trade, close_trade, get_conn
            # This partial row is a synthetic "half sold" trade — carry over
            # the SAME annotations_json as the parent position rather than a
            # fresh snapshot, since its entry story is the parent's entry.
            partial_id = insert_trade(
                ticker          = trade["ticker"],
                contract_symbol = trade["contract_symbol"],
                option_type     = trade["option_type"],
                strike          = trade["strike"],
                expiry          = trade["expiry"],
                contracts       = _sold_qty,
                entry_price     = entry_price,
                entry_time      = trade["entry_time"] if isinstance(trade["entry_time"], datetime) else datetime.fromisoformat(trade["entry_time"]),
                entry_reason    = trade.get("entry_reason", ""),
                paper           = paper,
                strategy_id     = trade.get("strategy_id", "INST_ORB"),
                annotations_json= trade.get("annotations_json"),
            )
            partial_pnl = close_trade(
                trade_id             = partial_id,
                exit_price           = fill_price,
                exit_time            = _now_et().replace(tzinfo=None),
                exit_reason          = f"{reason.split(' ')[0]}_profit_take",  # 2026-07-21: real trigger tag, not hardcoded
                confirmed_fill_price = fill_price,
                paper                = paper,
                annotations_json     = _snapshot_exit_annotations(trade.get("ticker", "")),
            )

            with get_conn() as _conn:
                _conn.execute(
                    "UPDATE trades SET contracts = ? WHERE id = ?",
                    (trade["contracts"] - _sold_qty, trade["id"]),
                )

            log_event(
                "INFO", "trading_logic",
                f"🟢 Took 50% profit — sold {_sold_qty} contract"
                f"{'s' if _sold_qty != 1 else ''} at ${fill_price:.2f} "
                f"(+${partial_pnl:.2f}). ATR/swing trailing stop now active on remainder.",
            )

            # ── AI reasoning layer (phase 1 — narration only) ─────────────────
            # Fires HERE, after close_trade() above confirmed the partial fill
            # actually happened — not back when should_exit() first went True.
            # partial_id is the trade row that actually closed (this sold
            # half), so that's what trade_id references, not the still-open
            # parent. Fire-and-forget: no-ops instantly if disabled, never
            # adds latency, zero effect on the trade that already executed.
            try:
                from ai_reasoning.narrator import narrate_exit
                _elapsed_min = (
                    (now_et - entry_time).total_seconds() / 60 if entry_time else 0.0
                )
                narrate_exit(
                    ticker           = ticker,
                    trade_id         = partial_id,
                    contract_symbol  = trade["contract_symbol"],
                    strategy_id      = trade.get("strategy_id"),
                    direction        = direction,
                    reason           = reason,
                    entry_price      = entry_price,
                    current_price    = fill_price,
                    elapsed_minutes  = _elapsed_min,
                    mtf_notes        = _mtf_notes,
                    peak_price       = ps.get("peak_price"),
                    min_price        = ps.get("min_price"),
                )
            except Exception as _ai_ex:
                logger.debug("ai_reasoning narrate_exit dispatch failed (non-fatal): %s", _ai_ex)

            from config import STAGE2_TRAIL_PCT
            ps["stage1_done"]     = True
            ps["stage1_be_price"] = round(entry_price * (1.0 + STAGE2_TRAIL_PCT), 4)

        else:
            # Full exit for all other reasons. mtf_notes threaded through so
            # _close_position() can narrate the confirmed close itself, once
            # it's actually confirmed — see that function for why this can't
            # just be narrated here before we know the close order succeeded.
            _close_position(alpaca, trade, current_price, reason,
                             bid_price=bid_price, mtf_notes=_mtf_notes)

    except Exception as e:
        from database import log_event
        logger.error("Error managing position: %s", e)
        log_event("ERROR", "trading_logic",
                  f"🔴 Error monitoring position: {type(e).__name__}. "
                  f"Will retry next tick. ({e})")


def _close_position(
    alpaca: "AlpacaClient",
    trade: dict,
    exit_price: float,
    reason: str,
    bid_price: Optional[float] = None,
    mtf_notes: Optional[list] = None,
) -> None:
    # Same fix as _manage_open_position above — resolve per-user state/risk/
    # logger fresh instead of reading trading.entry's module-level globals.
    _US        = get_user_state()
    _risk      = get_user_risk()
    _trade_log = get_user_trade_log()

    from config import (
        get_settings, get_risk_tier,
        STARTING_CAPITAL,
        BOOTSTRAP_RISK_PCT,
        GROWTH_MODE_RISK_PCT as _GMT_TL,
        MID_TIER_RISK_PCT as _MTT_TL,
    )
    from database import log_event, close_trade, get_open_trades, get_all_trades
    from risk import DailyLossLimitReached
    from tax_engine import record_sweep

    settings = get_settings()
    paper    = settings.get("paper_trading", True)

    _balance_close  = _US.get("account_balance", STARTING_CAPITAL)
    _rpct_close     = get_risk_tier(_balance_close)
    _tier_label = (
        "Tier4_5pct" if _rpct_close >= BOOTSTRAP_RISK_PCT else
        "Tier3_3pct" if _rpct_close >= _GMT_TL else
        "Tier2_2pct" if _rpct_close >= _MTT_TL else
        "Tier1_1pct"
    )

    if paper:
        logger.info("[PAPER] SELL %s @ $%.4f (%s)", trade["contract_symbol"], exit_price, reason)
    # Limit sell at mid-price (exit_price = quote["mid"]) — same favorable fill
    # as paper trading.  On live, if not filled in 5s, _wait_for_fill steps DOWN
    fill = alpaca.place_option_order(
        symbol          = trade["contract_symbol"],
        qty             = trade["contracts"],
        side            = "sell",
        order_type      = "limit",
        limit_price     = exit_price,   # mid price
        step_to_price   = bid_price,    # step down to bid on live if mid not taken
        position_intent = "sell_to_close",
    )

    # If the exit order didn't fill at all, leave the trade open and retry next tick.
    # Record actual worst-case exit fill, not the intended mid-price.
    if fill is None:
        if _reconcile_if_phantom(alpaca, trade):
            return
        log_event("WARNING", "trading_logic",
                  f"⚠️ [{trade['contract_symbol']}] Exit order did not fill — "
                  f"trade stays open, will retry next tick.")
        return

    # Use actual broker fill price; fall back to mid only if broker didn't report one
    fill_price = float(fill.get("confirmed_fill_price") or
                       fill.get("filled_avg_price") or exit_price)

    # FIX 2026-07-20 (Alpaca fills audit): broker.py may now return a PARTIAL
    # fill result for an exit order (fewer contracts closed than requested)
    # instead of either None or a full fill. Previously this whole function
    # assumed a "not None" fill meant ALL of trade["contracts"] closed, and
    # called close_trade() on the full row — which marks the trade "closed"
    # in the DB while Alpaca still holds a real, smaller remainder open. That
    # remainder would then never be tracked/monitored/risk-managed again.
    # Mirror the stage-1 partial-exit pattern: record only what actually
    # closed, shrink the parent row's contracts, and leave it OPEN so the
    # next tick's _manage_open_position re-evaluates the true remainder.
    _closed_qty = int(fill.get("filled_qty") or trade["contracts"])
    if _closed_qty < 1:
        log_event(
            "WARNING", "trading_logic",
            f"🟡 [{trade['contract_symbol']}] Exit order reported filled but 0 "
            f"contracts actually closed — trade stays open, will retry next tick.",
        )
        return
    if _closed_qty < trade["contracts"]:
        _remaining_qty = trade["contracts"] - _closed_qty
        log_event(
            "WARNING", "trading_logic",
            f"🟡 [{trade['contract_symbol']}] Exit only filled {_closed_qty} of "
            f"{trade['contracts']} contract(s) — closing the filled portion and "
            f"leaving {_remaining_qty} contract(s) open, will retry the "
            f"remainder next tick.",
        )
        logger.warning(
            "partial_fill_exit: trade_id=%s requested=%d filled=%d",
            trade["id"], trade["contracts"], _closed_qty,
        )
        from database import insert_trade, get_conn
        _trade_ps_partial = _US["positions"].get(trade["id"], {})
        partial_id = insert_trade(
            ticker          = trade["ticker"],
            contract_symbol = trade["contract_symbol"],
            option_type     = trade["option_type"],
            strike          = trade["strike"],
            expiry          = trade["expiry"],
            contracts       = _closed_qty,
            entry_price     = trade.get("entry_price", 0),
            entry_time      = trade["entry_time"] if isinstance(trade["entry_time"], datetime) else datetime.fromisoformat(trade["entry_time"]),
            entry_reason    = trade.get("entry_reason", ""),
            paper           = paper,
            strategy_id     = trade.get("strategy_id", "INST_ORB"),
            annotations_json= trade.get("annotations_json"),
        )
        close_trade(
            trade_id             = partial_id,
            exit_price           = exit_price,
            exit_time            = _now_et(),
            exit_reason          = reason,
            confirmed_fill_price = fill_price,
            peak_price           = _trade_ps_partial.get("peak_price"),
            mae_price            = _trade_ps_partial.get("min_price"),
            paper                = paper,
            annotations_json     = _snapshot_exit_annotations(trade.get("ticker", "")),
        )

        # ── AI reasoning layer (phase 1 — narration only) ─────────────────────
        # Fires HERE, after close_trade() above confirmed the filled portion
        # actually closed — partial_id is the row that closed, so that's the
        # trade_id referenced, not the parent (which stays open for the
        # unfilled remainder and will get its own narration when IT closes).
        try:
            from ai_reasoning.narrator import narrate_exit
            _pf_direction = "bullish" if (trade.get("option_type") or "call").lower() == "call" else "bearish"
            _pf_elapsed_min = 0.0
            try:
                _pf_entry_dt = trade["entry_time"] if isinstance(trade["entry_time"], datetime) else datetime.fromisoformat(str(trade["entry_time"]))
                _pf_elapsed_min = (_now_et().replace(tzinfo=None) - _pf_entry_dt.replace(tzinfo=None)).total_seconds() / 60
            except Exception:
                pass
            narrate_exit(
                ticker           = trade.get("ticker", "?"),
                trade_id         = partial_id,
                contract_symbol  = trade["contract_symbol"],
                strategy_id      = trade.get("strategy_id"),
                direction        = _pf_direction,
                reason           = reason,
                entry_price      = trade.get("entry_price", 0),
                current_price    = fill_price,
                elapsed_minutes  = _pf_elapsed_min,
                mtf_notes        = mtf_notes,
                peak_price       = _trade_ps_partial.get("peak_price"),
                min_price        = _trade_ps_partial.get("min_price"),
            )
        except Exception as _ai_ex:
            logger.debug("ai_reasoning narrate_exit dispatch failed (non-fatal): %s", _ai_ex)

        with get_conn() as _conn:
            _conn.execute(
                "UPDATE trades SET contracts = ? WHERE id = ?",
                (_remaining_qty, trade["id"]),
            )
        return

    # Pull MFE (peak_price) and MAE (min_price) from live position state so they
    # get saved to the DB and appear in the Journal's efficiency columns.
    _trade_ps = _US["positions"].get(trade["id"], {})
    _peak_px  = _trade_ps.get("peak_price")   # MFE: highest option mid-price seen
    _min_px   = _trade_ps.get("min_price")    # MAE: lowest  option mid-price seen

    # ── Generate post-trade recap (stored in DB; displayed in Journal) ────────
    # Build a one-paragraph natural-language summary of the trade so users
    # can review what happened without digging through the raw log.
    _entry_px   = float(trade.get("entry_price", 0) or 0)
    _contracts  = int(trade.get("contracts", 1) or 1)
    _ticker_r   = trade.get("ticker", "?")
    _strat_r    = trade.get("strategy_id", "?")
    _opt_r      = (trade.get("option_type") or "option").upper()
    _REASON_MAP = {
        # 2026-07-21: was "stage1_50pct" only — stage1 now has 4 possible
        # dynamic sub-triggers (ATR target / momentum fade / volume fade /
        # static-% fallback), so this matches any of them via the shared
        # "stage1" substring rather than the one flat-% string.
        "stage1":                   "Stage 1 profit-lock hit (dynamic trigger) — bot locked in half the position and moved the stop to breakeven",
        "stage2_break_even":        "Stop-to-breakeven triggered — the remainder exited at no loss after Stage 1 ran",
        "stage2_trail_stop":        "Trailing stop activated after locking in profit — price pulled back and the floor was hit",
        "atr_trail_stop":           "ATR/swing trailing stop tightened and triggered as price pulled back from the high",
        # Added 2026-07-18 alongside the reason-string fix in risk.py — this is
        # the static initial stop firing before the real trail could arm (needs
        # 5min + 15% gain warmup), NOT a trailing-stop failure. Was previously
        # mislabeled "atr_trail_stop" — see diag_instant_reversals.py.
        "initial_atr_stop":         "Initial ATR-based stop hit early — the trade moved against us before the trailing stop could arm",
        "vwap_trend_dead":          "VWAP breach plus trend breakdown confirmed — bot exited to avoid a larger loss",
        "structural_stop_bar_high": "Structural stop hit at the rejection level — the setup invalidated",
        "time_cap_loser":           "20-minute time cap hit without a confirming move — flat/losing trade closed to free capital",
        "time_cap_winner":          "90-minute maximum hold cap reached — winner closed to avoid late-day decay",
        "manual":                   "manually closed by the user",
        "panic":                    "emergency close triggered (kill-switch or account risk limit)",
        "kill_lock_force_close":    "daily loss limit reached — all positions force-closed to protect the account",
        # 2026-07-22: simplified 3-rule exit engine (see trading/simplified_exit_live.py)
        "simplified_hard_stop":       "hard stop hit — structural or ATR-based catastrophe stop",
        "simplified_chandelier_3atr": "chandelier exit (3.0x ATR trailing stop) triggered as price pulled back from the high",
        "simplified_time_cap":        "time cap hit — trade closed to stop theta bleed on a stalled position",
    }
    _reason_txt = next((v for k, v in _REASON_MAP.items() if reason and k in reason), reason or "exit signal")
    _pnl_sign   = "+" if 0 >= 0 else ""   # placeholder; real pnl not available yet
    _dur_secs   = 0
    try:
        from datetime import datetime as _dt
        _et_str = trade.get("entry_time", "")
        if _et_str:
            _entry_dt = _dt.fromisoformat(str(_et_str).replace("Z", "+00:00"))
            _dur_secs = int((_now_et().replace(tzinfo=None) - _entry_dt.replace(tzinfo=None)).total_seconds())
    except Exception:
        _dur_secs = 0
    _dur_txt = (
        f"{_dur_secs // 60}m {_dur_secs % 60}s" if _dur_secs < 3600
        else f"{_dur_secs // 3600}h {(_dur_secs % 3600) // 60}m"
    ) if _dur_secs > 0 else "unknown duration"
    _mfe_txt  = f" — the option peaked at ${_peak_px:.2f} ({round((_peak_px - _entry_px) / _entry_px * 100, 1):+.1f}% from entry)" if _peak_px and _entry_px > 0 else ""
    _mae_txt  = f", dipped as low as ${_min_px:.2f} ({round((_min_px - _entry_px) / _entry_px * 100, 1):+.1f}%)" if _min_px and _entry_px > 0 else ""
    _recap = (
        f"Strategy: {_strat_r} | {_ticker_r} {_opt_r} | "
        f"Entry ${_entry_px:.2f} → Exit ${fill_price:.2f} | "
        f"{_contracts} contract{'s' if _contracts != 1 else ''} | Hold: {_dur_txt}. "
        f"Exit: {_reason_txt}{_mfe_txt}{_mae_txt}."
    )

    pnl = close_trade(
        trade_id             = trade["id"],
        exit_price           = exit_price,
        exit_time            = _now_et(),
        exit_reason          = reason,
        confirmed_fill_price = fill_price,
        peak_price           = _peak_px,
        mae_price            = _min_px,
        paper                = paper,
        recap                = _recap,
        annotations_json     = _snapshot_exit_annotations(trade.get("ticker", "")),
    )

    # Human-readable close narrative
    try:
        _ticker_close = trade.get("ticker", "?")
        _opt_close    = trade.get("option_type", "option").upper()
        _entry_px     = trade.get("entry_price", 0)
        _pnl_sign     = "+" if pnl >= 0 else ""
        _reason_map   = {
            # 2026-07-21: see _REASON_MAP note above — matches any stage1
            # dynamic sub-trigger, not just the old flat +50%.
            "stage1":                    "first profit target hit (dynamic trigger)",
            "stage2_break_even":         "remainder hit break-even stop",
            "stage2_trail_stop":         "trail stop triggered (locked profit floor)",
            "atr_trail_stop":            "ATR/swing trailing stop hit",
            "initial_atr_stop":          "initial ATR stop hit early (before trail could arm)",
            "vwap_trend_dead":           "VWAP breach + trend breakdown confirmed",
            "structural_stop_bar_high":  "structural stop (rejection level) hit",
            "time_cap_loser":            "20-min cap (flat/losing — no setup confirmation)",
            "time_cap_winner":           "90-min cap (maximum hold for winners)",
            "manual":                    "manually closed by user",
            "panic":                     "emergency close triggered",
            "kill_lock_force_close":     "daily loss limit — force closed",
            "simplified_hard_stop":       "hard stop (structural/ATR)",
            "simplified_chandelier_3atr": "chandelier exit (3.0x ATR trail)",
            "simplified_time_cap":        "time cap (theta stall)",
        }
        _reason_nice = next(
            (v for k, v in _reason_map.items() if reason and k in reason), reason or "exit signal"
        )
        _mode_tag = "[PAPER] " if paper else ""
        _emoji    = "🟢" if pnl >= 0 else "🔴"
        log_event(
            "INFO", "trading_logic",
            f"{_emoji} {_mode_tag}EXIT — Sold {_ticker_close} {_opt_close} "
            f"@ ${fill_price:.2f} (trigger ${exit_price:.2f}, entry ${_entry_px:.2f}). "
            f"P&L: {_pnl_sign}${pnl:.2f}. Reason: {_reason_nice}.",
        )
    except Exception:
        pass

    # ── AI reasoning layer (phase 1 — narration only) ─────────────────────────
    # Fires HERE, after close_trade() above confirmed the full exit actually
    # happened — not back when should_exit() first went True (that was the
    # bug: a slow/rejected/retried close order would re-trigger narration on
    # every following tick for a position that never actually closed).
    # _dur_secs was already computed above for the post-trade recap — reused
    # here instead of recomputing the same elapsed-time math a second time.
    try:
        from ai_reasoning.narrator import narrate_exit
        _close_direction = "bullish" if (trade.get("option_type") or "call").lower() == "call" else "bearish"
        narrate_exit(
            ticker           = trade.get("ticker", "?"),
            trade_id         = trade["id"],
            contract_symbol  = trade["contract_symbol"],
            strategy_id      = trade.get("strategy_id"),
            direction        = _close_direction,
            reason           = reason,
            entry_price      = _entry_px,
            current_price    = fill_price,
            elapsed_minutes  = _dur_secs / 60.0,
            mtf_notes        = mtf_notes,
            peak_price       = _peak_px,
            min_price        = _min_px,
        )
    except Exception as _ai_ex:
        logger.debug("ai_reasoning narrate_exit dispatch failed (non-fatal): %s", _ai_ex)

    if pnl > 0:
        try:
            reserved = record_sweep(pnl, trade["id"])
            _US["last_tax_sweep"] = reserved
        except Exception as e:
            logger.error("Tax sweep failed: %s", e)

    try:
        _risk.record_pnl(pnl, account_balance=_US["account_balance"])
    except DailyLossLimitReached:
        raise

    # Recompute session P&L from DB
    try:
        _US["session_pnl"] = sum(
            (t.get("realized_pnl") or 0)
            for t in get_all_trades(limit=100)
            if (t.get("exit_time") or "")[:10] == date.today().isoformat()
        )
    except Exception:
        pass

    closed_utc = _now_et()
    _closed_opt_type  = trade.get("option_type", "")
    _closed_direction = "bullish" if _closed_opt_type == "call" else "bearish"

    # Clear per-trade state
    _US["positions"].pop(trade["id"], None)

    _remaining_open               = get_open_trades()
    _US["open_trades"]     = _remaining_open
    _US["open_trade"]      = _remaining_open[0] if _remaining_open else None
    _US["status"]          = "in_trade" if _remaining_open else "scanning"
    _US["last_direction"]        = _closed_direction
    _US["last_trade_closed_time"]= closed_utc.isoformat()

    _closed_ticker = trade.get("ticker", "")
    if pnl > 0 and _closed_ticker:
        _WIN_COOLDOWN_MIN = 10
        _win_expires = _now_et() + timedelta(minutes=_WIN_COOLDOWN_MIN)
        _US.setdefault("ticker_win_cooldown", {})[_closed_ticker] = _win_expires
        log_event("INFO", "trading_logic",
                  f"⏱ [{_closed_ticker}] Post-win cooldown {_WIN_COOLDOWN_MIN} min "
                  f"(pnl=${pnl:+.2f}). No re-entry until {_win_expires.strftime('%H:%M')} ET.")

    # ── Per-ticker post-loss quality gate ────────────────────────────────────
    # After a loss, record exit price/direction for the 0.3% displacement check
    # in entry.py.  Also set a STRUCTURAL cooldown keyed by ticker:strategy_id
    _strat_id = trade.get("strategy_id", "")
    if pnl < 0 and _closed_ticker:
        _US.setdefault("ticker_loss_context", {})[_closed_ticker] = {
            "exit_price":   exit_price,
            "direction":    _closed_direction,
            "strategy_id":  _strat_id,
            "loss_count":   _US.get("ticker_loss_context", {}).get(
                                _closed_ticker, {}).get("loss_count", 0) + 1,
        }


    # Remove from bot_state.json open_positions
    try:
        import json as _json_cl
        _state_path_cl = get_bot_state_path()
        if _state_path_cl.exists():
            with open(_state_path_cl) as _f:
                _existing_cl = _json_cl.load(_f)
            _open_positions_cl = _existing_cl.get("open_positions") or {}
            _open_positions_cl.pop(str(trade["id"]), None)
            _existing_cl["open_positions"] = _open_positions_cl
            with open(_state_path_cl, "w") as _f:
                _json_cl.dump(_existing_cl, _f)
    except Exception:
        pass

    # Flip-trade arming
    from config import get_settings as _gs
    _is_hard_stop         = "stop" in (reason or "")
    _flip_setting_enabled = bool(_gs().get("flip_trading_enabled", True))
    if _is_hard_stop and _flip_setting_enabled:
        _flip_dir = "bearish" if _closed_direction == "bullish" else "bullish"
        _US["flip_eligible"]  = True
        _US["flip_direction"] = _flip_dir
        _US["flip_ticker"]    = _closed_ticker
        log_event("INFO", "trading_logic",
                  f"🟡 Flip armed — stopped out {_closed_direction}. "
                  f"Watching for {_flip_dir} retest entry.")
    else:
        _US["flip_eligible"]  = False
        _US["flip_direction"] = None
        _US["flip_ticker"]    = None

    _trade_log.info(
        "trade_closed",
        extra={
            "event":                   "trade_closed",
            "Trade_ID":                trade["id"],
            "Risk_Tier_Used":          _tier_label,
            "R_R_Ratio":               "n/a",
            "Entry_Volume_Multiplier": "n/a",
            "exit_price":   round(exit_price, 4),
            "realized_pnl": round(pnl, 2),
            "exit_reason":  reason,
            "flip_armed":   _is_hard_stop and _flip_setting_enabled,
        },
    )
    if hasattr(_trade_log, "clear_context"):
        _trade_log.clear_context()
    set_user_trade_log(logger)   # trade closed — reset this user's logger to plain
