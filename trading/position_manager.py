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
  7. Time cap of last resort — 90 min for winners, 20 min for flat/losing
     (safety net only; structure-based exits should fire first)

Per-position state machine keys (stored in LIVE_STATE["positions"][trade_id]):
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

from trading.state import LIVE_STATE, _now_et, _ET_TZ, _BOT_ROOT

logger = logging.getLogger("celo_trader.trading_logic")

# ── ATR / swing trailing stop constants ──────────────────────────────────────
_ATR_TRAIL_MULTIPLIER = 2.0   # stop = peak − 2.0 × ATR (underlying space)
                               # Widened from 1.5: 7–21 DTE options need room for
                               # intraday wicks without getting chopped off healthy
                               # pullbacks before the daily trend can develop.
_DELTA_APPROX         = 0.40  # approximate option delta for underlying→option conversion
_SWING_LOOKBACK       = 20    # bars to look back for swing high/low

# ── VWAP breach + trend breakdown constants ───────────────────────────────────
_ADX_WEAK_THRESHOLD   = 20    # ADX < 20 → trend has no directional strength
_EMA_FAST             = 8
_EMA_MID              = 21
_EMA_SLOW             = 50
_VWAP_BREACH_BARS     = 5     # VWAP must be breached for ≥ 5 consecutive 1-min bars
                               # (= 5 minutes) before we check trend. 2 was too fast —
                               # a 2-minute dip below VWAP during normal chop triggered
                               # the exit before the trade had any chance to develop.
# ── Time cap of last resort (safety net only) ─────────────────────────────────
_TIME_CAP_WINNER_MIN  = 90    # stage1 done  → 90 min max
_TIME_CAP_LOSER_MIN   = 20    # flat/losing  → 20 min max

# ── ATR trail warmup ──────────────────────────────────────────────────────────
# Don't arm the ATR trailing stop until the trade is at least this many minutes
# old. On 1-min bars, the entry-bar ATR and swing levels are right at current
# price, so the stop fires almost immediately on any noise. A 5-min warmup gives
# the trade room to breathe before the structural trail kicks in.
_MIN_TRAIL_WARMUP_MIN = 5


# ── Indicator helpers ─────────────────────────────────────────────────────────

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


def _compute_adx(df: pd.DataFrame, period: int = 14) -> Optional[float]:
    """
    Wilder's ADX on 1-min bars.
    ADX < 20 = no directional trend (choppy / ranging).
    """
    try:
        if len(df) < period * 2:
            return None
        high  = df["high"].values.astype(float)
        low   = df["low"].values.astype(float)
        close = df["close"].values.astype(float)

        # True Range
        tr = np.maximum(
            high[1:] - low[1:],
            np.maximum(np.abs(high[1:] - close[:-1]), np.abs(low[1:] - close[:-1]))
        )

        # Directional movement
        plus_dm  = np.where((high[1:] - high[:-1]) > (low[:-1] - low[1:]),
                             np.maximum(high[1:] - high[:-1], 0), 0)
        minus_dm = np.where((low[:-1] - low[1:]) > (high[1:] - high[:-1]),
                             np.maximum(low[:-1] - low[1:], 0), 0)

        # Wilder smoothing (EMA with alpha = 1/period)
        def wilder_smooth(arr, n):
            out = np.zeros(len(arr))
            out[0] = arr[:n].sum()
            for i in range(1, len(arr)):
                out[i] = out[i-1] - out[i-1] / n + arr[i]
            return out

        atr_w  = wilder_smooth(tr, period)
        pdm_w  = wilder_smooth(plus_dm, period)
        mdm_w  = wilder_smooth(minus_dm, period)

        with np.errstate(divide="ignore", invalid="ignore"):
            pdi    = np.where(atr_w > 0, 100 * pdm_w / atr_w, 0)
            mdi    = np.where(atr_w > 0, 100 * mdm_w / atr_w, 0)
            dx_den = pdi + mdi
            dx     = np.where(dx_den > 0, 100 * np.abs(pdi - mdi) / dx_den, 0)

        adx_w  = wilder_smooth(dx[period:], period)
        return float(adx_w[-1]) if len(adx_w) > 0 else None
    except Exception as ex:
        logger.debug("ADX computation failed: %s", ex)
        return None


def _ema_stack_aligned(df: pd.DataFrame, direction: str) -> bool:
    """
    True if the EMA stack is aligned in the trade direction.

    Bullish (CALL): EMA8 > EMA21 > EMA50 — all stacked up
    Bearish (PUT) : EMA8 < EMA21 < EMA50 — all stacked down

    Misalignment means the trend is breaking down and VWAP breach is meaningful.
    """
    try:
        if len(df) < _EMA_SLOW + 5:
            return True   # insufficient data → assume aligned (don't exit prematurely)
        close = df["close"]
        ema8  = float(close.ewm(span=_EMA_FAST, adjust=False).mean().iloc[-1])
        ema21 = float(close.ewm(span=_EMA_MID,  adjust=False).mean().iloc[-1])
        ema50 = float(close.ewm(span=_EMA_SLOW, adjust=False).mean().iloc[-1])
        if direction == "bullish":
            return ema8 > ema21 > ema50
        else:
            return ema8 < ema21 < ema50
    except Exception:
        return True


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
    from trading import entry as _em

    try:
        # ── Option quote ──────────────────────────────────────────────────────
        quote = tradier.get_option_quote(trade["contract_symbol"])
        if quote is None:
            logger.warning("Cannot price %s — holding", trade["contract_symbol"])
            return

        current_price = quote["mid"]
        entry_price   = trade["entry_price"]
        trade_id      = trade["id"]
        ticker        = trade.get("ticker", "")
        option_type   = (trade.get("option_type") or "call").lower()
        direction     = "bullish" if option_type == "call" else "bearish"

        # ── Per-position state ────────────────────────────────────────────────
        ps = LIVE_STATE["positions"].setdefault(trade_id, {
            "peak_price":                None,   # MFE: highest option price seen
            "min_price":                 None,   # MAE: lowest  option price seen (adverse)
            "entry_time":                trade.get("entry_time"),
            "stage1_done":               False,
            "stage1_be_price":           None,
            "current_stop_pct":          _em._risk.ORB_STOP_PCT if _em._risk else 0.20,
            "struct_stop_price":         None,
            "current_option_price":      None,
            "current_option_price_time": None,
            "last_position_narration_minute": None,
            # Adaptive state machine
            "atr_trail_stop":            None,
            "vwap_breached_bars":        0,     # consecutive bars below/above VWAP
            "peak_underlying":           None,  # highest underlying close for trail calc
            "last_bar_fetch_minute":     None,  # throttle: fetch bars max once/minute
            "cached_underlying_df":      None,  # cache to avoid refetching every tick
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

        # ── Compute adaptive trailing stop from bars ───────────────────────────
        atr_trail_stop: Optional[float]  = ps.get("atr_trail_stop")
        vwap: Optional[float]            = None
        trend_dead: bool                 = False
        _rvol_for_exit: float            = 0.0   # passed to momentum-death check in risk.py

        # Trade age in minutes — used to gate the ATR trail warmup
        _trade_age_min = (
            (now_et - entry_time).total_seconds() / 60
            if entry_time else 999.0
        )

        if df_under is not None and not df_under.empty:
            _underlying_now = float(df_under["close"].iloc[-1])

            # ATR-based trailing stop in underlying space.
            # WARMUP GUARD: don't arm until _MIN_TRAIL_WARMUP_MIN minutes have
            # elapsed.  On 1-min bars the entry-bar ATR/swing is essentially at
            # current price, so the stop fires on first-minute noise otherwise.
            _atr = _compute_atr(df_under)
            # PROFIT GATE: only arm the ATR trail once the option is at least
            # 15% above entry.  Before that threshold the underlying has barely
            # moved, so the ATR stop sits essentially at entry price — any normal
            # wiggle fires the trail at break-even or a loss despite positive MFE.
            _opt_gain_pct = (current_price - entry_price) / entry_price if entry_price else 0.0
            _trail_profit_gate = _opt_gain_pct >= 0.15
            if (_atr is not None
                    and ps.get("peak_underlying") is not None
                    and _trade_age_min >= _MIN_TRAIL_WARMUP_MIN
                    and _trail_profit_gate):
                _peak_u = float(ps["peak_underlying"])
                if direction == "bullish":
                    _atr_stop_u = _peak_u - _ATR_TRAIL_MULTIPLIER * _atr
                else:
                    _atr_stop_u = _peak_u + _ATR_TRAIL_MULTIPLIER * _atr

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

            # RVOL proxy for momentum-death exit check in risk.py
            # Raw current/avg volume from the underlying bars (no indicators needed).
            try:
                _curr_vol = float(df_under["volume"].iloc[-1])
                _avg_vol  = float(df_under["volume"].iloc[-20:].mean()) if len(df_under) >= 5 else _curr_vol
                _rvol_for_exit = _curr_vol / _avg_vol if _avg_vol > 0 else 0.0
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

            # Trend breakdown check — only when VWAP breach is sustained
            if ps.get("vwap_breached_bars", 0) >= _VWAP_BREACH_BARS:
                _adx   = _compute_adx(df_under)
                _ema_ok = _ema_stack_aligned(df_under, direction)
                adx_weak    = (_adx is not None and _adx < _ADX_WEAK_THRESHOLD)
                ema_broken  = not _ema_ok
                # Require BOTH conditions — ADX<20 alone is common during normal
                # mid-morning consolidation and should not terminate a live trade.
                # EMA misalignment alone can be transient. Both together = confirmed dead.
                trend_dead  = adx_weak and ema_broken

        # Persist current stop for dashboard visibility
        _current_stop_pct_display = (
            round(1.0 - atr_trail_stop / entry_price, 4) if atr_trail_stop else
            (_em._risk.ORB_STOP_PCT if _em._risk else 0.20)
        )
        ps["current_stop_pct"] = _current_stop_pct_display

        # ── Write to bot_state.json ───────────────────────────────────────────
        import json as _json_m
        _state_path_m = _BOT_ROOT / "bot_state.json"
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
                "vwap_breached_bars":        ps.get("vwap_breached_bars", 0),
                "trend_dead":                trend_dead,
            }
            _existing["open_positions"]             = _open_positions
            _existing["current_stop_pct"]           = _current_stop_pct_display
            _existing["current_option_price"]       = current_price
            _existing["current_option_price_time"]  = ps["current_option_price_time"]
            # Always carry the latest session_pnl so the WebSocket never reads a stale value
            _existing["session_pnl"]                = LIVE_STATE.get("session_pnl", 0.0)
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
        should_exit, reason = _em._risk.should_exit(
            entry_price, current_price,
            entry_time      = entry_time,
            now             = now_et,
            stage1_done     = stage1_done,
            stage1_be_price = stage1_be_price,
            struct_stop_price = _struct_stop,
            atr_trail_stop  = atr_trail_stop,
            vwap            = vwap,
            trend_dead      = trend_dead,
            direction       = direction,
            rvol            = _rvol_for_exit,
        )

        if not should_exit:
            return

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
                _close_position(alpaca, trade, current_price,
                                "stage1_50pct_full_exit_single_contract")
                return

            from config import get_settings
            settings = get_settings()
            paper    = settings.get("paper_trading", True)

            if paper:
                _em._trade_log.info(
                    "stage1_partial_exit",
                    extra={
                        "event":          "stage1_partial_exit",
                        "contracts_sold": half_contracts,
                        "exit_price":     round(current_price, 4),
                        "entry_price":    round(entry_price, 4),
                    },
                )
            fill = alpaca.place_option_order(
                symbol     = trade["contract_symbol"],
                qty        = half_contracts,
                side       = "sell",
                order_type = "market",
            )

            if fill is None:
                log_event(
                    "WARNING", "trading_logic",
                    f"🟡 [{trade['contract_symbol']}] Stage-1 profit-take order "
                    f"did not fill — leaving at full size, will retry next tick.",
                )
                return

            fill_price = float(fill.get("filled_avg_price") or current_price)

            from database import insert_trade, close_trade, get_conn
            partial_id = insert_trade(
                ticker          = trade["ticker"],
                contract_symbol = trade["contract_symbol"],
                option_type     = trade["option_type"],
                strike          = trade["strike"],
                expiry          = trade["expiry"],
                contracts       = half_contracts,
                entry_price     = entry_price,
                entry_time      = trade["entry_time"] if isinstance(trade["entry_time"], datetime) else datetime.fromisoformat(trade["entry_time"]),
                entry_reason    = trade.get("entry_reason", ""),
                paper           = paper,
                strategy_id     = trade.get("strategy_id", "INST_ORB"),
            )
            partial_pnl = close_trade(
                trade_id             = partial_id,
                exit_price           = fill_price,
                exit_time            = _now_et().replace(tzinfo=None),
                exit_reason          = "stage1_50pct_profit_take",
                confirmed_fill_price = fill_price,
            )

            with get_conn() as _conn:
                _conn.execute(
                    "UPDATE trades SET contracts = ? WHERE id = ?",
                    (trade["contracts"] - half_contracts, trade["id"]),
                )

            log_event(
                "INFO", "trading_logic",
                f"🟢 Took 50% profit — sold {half_contracts} contract"
                f"{'s' if half_contracts > 1 else ''} at ${fill_price:.2f} "
                f"(+${partial_pnl:.2f}). ATR/swing trailing stop now active on remainder.",
            )

            from config import STAGE2_TRAIL_PCT
            ps["stage1_done"]     = True
            ps["stage1_be_price"] = round(entry_price * (1.0 + STAGE2_TRAIL_PCT), 4)

        else:
            # Full exit for all other reasons
            _close_position(alpaca, trade, current_price, reason)

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
) -> None:
    from trading import entry as _em

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

    _balance_close  = LIVE_STATE.get("account_balance", STARTING_CAPITAL)
    _rpct_close     = get_risk_tier(_balance_close)
    _tier_label = (
        "Tier4_5pct" if _rpct_close >= BOOTSTRAP_RISK_PCT else
        "Tier3_3pct" if _rpct_close >= _GMT_TL else
        "Tier2_2pct" if _rpct_close >= _MTT_TL else
        "Tier1_1pct"
    )

    if paper:
        logger.info("[PAPER] SELL %s @ $%.4f (%s)", trade["contract_symbol"], exit_price, reason)
    fill = alpaca.place_option_order(
        symbol     = trade["contract_symbol"],
        qty        = trade["contracts"],
        side       = "sell",
        order_type = "market",
    )

    fill_price = exit_price
    if fill and fill.get("filled_avg_price"):
        fill_price = float(fill["filled_avg_price"])

    # Pull MFE (peak_price) and MAE (min_price) from live position state so they
    # get saved to the DB and appear in the Journal's efficiency columns.
    _trade_ps = LIVE_STATE["positions"].get(trade["id"], {})
    _peak_px  = _trade_ps.get("peak_price")   # MFE: highest option mid-price seen
    _min_px   = _trade_ps.get("min_price")    # MAE: lowest  option mid-price seen

    pnl = close_trade(
        trade_id             = trade["id"],
        exit_price           = exit_price,
        exit_time            = _now_et(),
        exit_reason          = reason,
        confirmed_fill_price = fill_price,
        peak_price           = _peak_px,
        mae_price            = _min_px,
    )

    # Human-readable close narrative
    try:
        _ticker_close = trade.get("ticker", "?")
        _opt_close    = trade.get("option_type", "option").upper()
        _entry_px     = trade.get("entry_price", 0)
        _pnl_sign     = "+" if pnl >= 0 else ""
        _reason_map   = {
            "stage1_50pct":              "first profit target hit (+50%)",
            "stage2_break_even":         "remainder hit break-even stop",
            "stage2_trail_stop":         "trail stop triggered (locked profit floor)",
            "atr_trail_stop":            "ATR/swing trailing stop hit",
            "vwap_trend_dead":           "VWAP breach + trend breakdown confirmed",
            "structural_stop_bar_high":  "structural stop (rejection level) hit",
            "time_cap_loser":            "20-min cap (flat/losing — no setup confirmation)",
            "time_cap_winner":           "90-min cap (maximum hold for winners)",
            "manual":                    "manually closed by user",
            "panic":                     "emergency close triggered",
            "kill_lock_force_close":     "daily loss limit — force closed",
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

    if pnl > 0:
        try:
            reserved = record_sweep(pnl, trade["id"])
            LIVE_STATE["last_tax_sweep"] = reserved
        except Exception as e:
            logger.error("Tax sweep failed: %s", e)

    try:
        _em._risk.record_pnl(pnl, account_balance=LIVE_STATE["account_balance"])
    except DailyLossLimitReached:
        raise

    # Recompute session P&L from DB
    try:
        LIVE_STATE["session_pnl"] = sum(
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
    LIVE_STATE["positions"].pop(trade["id"], None)

    _remaining_open               = get_open_trades()
    LIVE_STATE["open_trades"]     = _remaining_open
    LIVE_STATE["open_trade"]      = _remaining_open[0] if _remaining_open else None
    LIVE_STATE["status"]          = "in_trade" if _remaining_open else "scanning"
    LIVE_STATE["last_direction"]        = _closed_direction
    LIVE_STATE["last_trade_closed_time"]= closed_utc.isoformat()

    _closed_ticker = trade.get("ticker", "")
    if pnl > 0 and _closed_ticker:
        _WIN_COOLDOWN_MIN = 10
        _win_expires = _now_et() + timedelta(minutes=_WIN_COOLDOWN_MIN)
        LIVE_STATE.setdefault("ticker_win_cooldown", {})[_closed_ticker] = _win_expires
        log_event("INFO", "trading_logic",
                  f"⏱ [{_closed_ticker}] Post-win cooldown {_WIN_COOLDOWN_MIN} min "
                  f"(pnl=${pnl:+.2f}). No re-entry until {_win_expires.strftime('%H:%M')} ET.")

    # ── Per-ticker post-loss quality gate ────────────────────────────────────
    # After a loss, record exit price/direction for the 0.3% displacement check
    # in entry.py.  Also set a STRUCTURAL cooldown keyed by ticker:strategy_id
    # so re-entry requires actual market conditions to reset, not just a timer.
    _strat_id = trade.get("strategy_id", "")
    if pnl < 0 and _closed_ticker:
        LIVE_STATE.setdefault("ticker_loss_context", {})[_closed_ticker] = {
            "exit_price":   exit_price,
            "direction":    _closed_direction,
            "strategy_id":  _strat_id,
            "loss_count":   LIVE_STATE.get("ticker_loss_context", {}).get(
                                _closed_ticker, {}).get("loss_count", 0) + 1,
        }


    # Remove from bot_state.json open_positions
    try:
        import json as _json_cl
        _state_path_cl = _BOT_ROOT / "bot_state.json"
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
        LIVE_STATE["flip_eligible"]  = True
        LIVE_STATE["flip_direction"] = _flip_dir
        LIVE_STATE["flip_ticker"]    = _closed_ticker
        log_event("INFO", "trading_logic",
                  f"🟡 Flip armed — stopped out {_closed_direction}. "
                  f"Watching for {_flip_dir} retest entry.")
    else:
        LIVE_STATE["flip_eligible"]  = False
        LIVE_STATE["flip_direction"] = None
        LIVE_STATE["flip_ticker"]    = None

    _em._trade_log.info(
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
    if hasattr(_em._trade_log, "clear_context"):
        _em._trade_log.clear_context()
    _em._trade_log = logger
