"""
risk/exits.py — Adaptive exit engine (structure-driven, not time-driven).

ExitsMixin — mixed into RiskManager (risk/manager.py). Split out of risk.py
(2026-08-01, file-size cleanup); no logic changed, only relocated. This is
the single most load-bearing function in the whole risk package — see the
docstring on evaluate_exit_conditions() for the full exit hierarchy and its
diagnosis history. Left as one function rather than split further: it's a
single ordered decision chain where each branch's placement in the sequence
is load-bearing (rule 6 — trade logic must stay one coherent path).
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from config import EARLY_TIMEBOX_MIN, EARLY_STOP_PCT, MOMENTUM_DEAD_RVOL, MOMENTUM_DEAD_MIN


class ExitsMixin:
    def evaluate_exit_conditions(
        self,
        entry_price: float,
        current_price: float,
        entry_time: Optional[datetime] = None,
        now: Optional[datetime] = None,
        stage1_done: bool = False,
        stage1_be_price: Optional[float] = None,
        peak_price: Optional[float] = None,         # highest option price seen (for giveback rule)
        struct_stop_price: Optional[float] = None,  # entry_bar_high/low-derived option stop
        # Adaptive exit params — supplied by position_manager's bar analysis
        atr_trail_stop: Optional[float] = None,     # tighter of 1.5×ATR or swing stop (option price)
        trail_armed: bool = False,                  # True = atr_trail_stop is the REAL armed
                                                     # trail; False = it's the initial_atr_stop
                                                     # fallback (trail hasn't armed yet). Added
                                                     # 2026-07-18 so the exit reason string can
                                                     # tell these apart — see note below.
        vwap: Optional[float] = None,               # current underlying VWAP
        vwap_breached: bool = False,                # True when VWAP breached ≥1 bar (no trend_dead required)
        trend_dead: bool = False,                   # ADX<20 OR EMA stack misaligned
        direction: str = "bullish",                 # trade direction (for VWAP side check)
        rvol: float = 0.0,                          # current bar RVOL (for momentum-death check)
        # Dynamic stage1 trigger inputs (2026-07-21) — precomputed by caller,
        # this function never touches raw bars/indicators directly.
        atr_target_price: Optional[float] = None,   # ATR-scaled stage1 target (option price)
        momentum_fading: bool = False,              # RSI exhaustion OR 5m MACD rollover
    ) -> tuple[bool, str]:
        """
        Adaptive exit engine — structure-driven, not time-driven.

        Exit hierarchy (checked in order):
          1. Structural stop  — entry_bar_high/low-derived option level (always on)
          2. ATR/swing trail  — tighter of 1.5×ATR below peak or last swing low/high
          3. VWAP + trend dead — breach + (ADX<20 OR EMA misalignment); NOT every dip
          4. Stage 1 target   — +50% option gain → partial exit signal
          5. Stage 2 trail    — entry×1.15 locked-profit floor on the runner
          6. Hard stop safety — 20% below entry (absolute net)
          7. Time cap (last resort) — 90m winners / config.EARLY_TIMEBOX_MIN
             flat-losers (currently 60m; see config.py, not this docstring)

        Time caps are LAST RESORT only. Structure-based exits (2, 3) should fire
        before the clock ever becomes relevant for a correctly-entered trade.
        """
        now = now or datetime.utcnow()

        # ── Elapsed time (for time-cap safety net only) ───────────────────────
        elapsed_minutes = 0.0
        if entry_time is not None:
            try:
                elapsed_minutes = max(0.0, (now - entry_time).total_seconds() / 60)
            except TypeError:
                _now_n = now.replace(tzinfo=None) if now.tzinfo else now
                _et_n  = entry_time.replace(tzinfo=None) if entry_time.tzinfo else entry_time
                elapsed_minutes = max(0.0, (_now_n - _et_n).total_seconds() / 60)

        # ── 1. Structural stop (entry bar high/low) ───────────────────────────
        if struct_stop_price is not None and current_price <= struct_stop_price:
            return True, (
                f"structural_stop_bar_high "
                f"(sl={struct_stop_price:.4f} current={current_price:.4f})"
            )

        # ── 2. ATR / swing trailing stop ──────────────────────────────────────
        # FIX 2026-07-18: this used to always return reason "atr_trail_stop"
        # regardless of whether the REAL armed trail fired or the static
        # initial_atr_stop fallback did (position_manager.py substitutes the
        # latter in before the trail can arm — needs 5min + 15% gain warmup).
        # `trail_armed` disambiguates the exit-reason string.
        if atr_trail_stop is not None:
            if current_price <= atr_trail_stop:
                _reason = "atr_trail_stop" if trail_armed else "initial_atr_stop"
                return True, (
                    f"{_reason} "
                    f"(trail={atr_trail_stop:.4f} current={current_price:.4f})"
                )
        else:
            hard_stop = entry_price * 0.80
            if current_price <= hard_stop:
                return True, f"hard_stop_20pct (sl={hard_stop:.4f} current={current_price:.4f})"

        # ── 3. VWAP breach + confirmed trend breakdown ────────────────────────
        # Only exits when trend_dead is True (VWAP breached ≥2 bars AND
        # ADX<20 or EMA misaligned, computed by position_manager against the
        # underlying) — NOT on every dip below VWAP.
        if vwap is not None and trend_dead:
            return True, f"vwap_trend_dead (trend_dead=True direction={direction})"

        # ── 3b. VWAP breach while profitable — take the money ────────────────
        if (not stage1_done
                and vwap_breached
                and current_price > entry_price * 1.05):
            profit_pct = (current_price / entry_price - 1.0) * 100
            return True, (
                f"vwap_breach_profitable "
                f"(profit={profit_pct:.1f}% VWAP breached — locking gain)"
            )

        # ── 3c. Peak-giveback exit ────────────────────────────────────────────
        # If trade reached +20% at peak and has given back >40% of that gain,
        # exit the runner rather than watch it evaporate.
        if (not stage1_done
                and peak_price is not None
                and peak_price >= entry_price * 1.20):
            gain_at_peak = peak_price - entry_price
            current_gain = current_price - entry_price
            giveback_pct = 1.0 - (current_gain / gain_at_peak) if gain_at_peak > 0 else 0.0
            if giveback_pct >= 0.40:
                return True, (
                    f"peak_giveback "
                    f"(peak={peak_price:.4f} +{gain_at_peak/entry_price*100:.1f}% "
                    f"gave_back={giveback_pct*100:.0f}% of gain)"
                )

        # ── 4. Stage 1: dynamic profit-lock trigger ──────────────────────────
        # Fires on whichever condition hits first — ATR-scaled target
        # (primary), momentum fade, or volume fade (gated by a minimum gain
        # floor). Falls back to the flat % only when ATR data is missing or
        # STAGE1_DYNAMIC_ENABLED is False (fail-open, same as the ATR trail).
        if not stage1_done:
            gain_pct = (current_price - entry_price) / entry_price if entry_price else 0.0

            if self.STAGE1_DYNAMIC_ENABLED and atr_target_price is not None:
                if current_price >= atr_target_price:
                    return True, (
                        f"stage1_atr_target "
                        f"(target={atr_target_price:.4f} current={current_price:.4f} +{gain_pct*100:.1f}%)"
                    )
                # Floor is a FRACTION OF THE TARGET DISTANCE, not a flat % of
                # premium — widens/tightens with volatility like the target.
                _target_dist = atr_target_price - entry_price
                _floor_price = entry_price + self.STAGE1_FLOOR_FRACTION_OF_TARGET * _target_dist
                if current_price >= _floor_price:
                    if momentum_fading:
                        return True, f"stage1_momentum_fade (+{gain_pct*100:.1f}%)"
                    if rvol > 0.0 and rvol < self.STAGE1_RVOL_FADE_THRESHOLD:
                        return True, (
                            f"stage1_volume_fade (rvol={rvol:.2f} +{gain_pct*100:.1f}%)"
                        )
            else:
                s1 = self.stage1_exit_price(entry_price)
                if current_price >= s1:
                    return True, f"stage1_static_fallback (target={s1:.4f} current={current_price:.4f})"

        # ── 5. Stage 2: locked-profit trail stop ─────────────────────────────
        if stage1_done and stage1_be_price is not None:
            if current_price <= stage1_be_price:
                return True, (
                    f"stage2_trail_stop "
                    f"(floor={stage1_be_price:.4f} current={current_price:.4f})"
                )

        # ── 6. Early momentum stop (first EARLY_TIMEBOX_MIN, before stage 1) ─
        # Fast failure detection: if down EARLY_STOP_PCT within
        # EARLY_TIMEBOX_MIN, the setup failed — exit before theta compounds.
        if not stage1_done and elapsed_minutes <= EARLY_TIMEBOX_MIN:
            early_stop = entry_price * (1.0 - EARLY_STOP_PCT)
            if current_price <= early_stop:
                return True, (
                    f"early_momentum_stop_{round(EARLY_STOP_PCT*100)}pct "
                    f"(floor={early_stop:.4f} current={current_price:.4f} "
                    f"held={elapsed_minutes:.1f}min)"
                )

        # ── 7. Time caps — LAST RESORT ONLY ──────────────────────────────────
        # Structure-based exits (2, 3) should fire before these in a healthy
        # trade. These exist only as a safety net against zombie positions.

        # Momentum-death: RVOL dropped below threshold AND the trade is
        # losing — institutional participation is gone, exit before theta.
        from config import MOMENTUM_DEAD_LOSS_PCT as _MDL
        if (not stage1_done
                and rvol > 0.0
                and rvol < MOMENTUM_DEAD_RVOL
                and elapsed_minutes >= MOMENTUM_DEAD_MIN
                and current_price <= entry_price * (1.0 - _MDL)):
            return True, (
                f"momentum_dead_exit "
                f"(rvol={rvol:.2f}<{MOMENTUM_DEAD_RVOL:.1f} "
                f"down {((current_price/entry_price)-1)*100:.1f}% held={elapsed_minutes:.1f}min)"
            )

        # Hard cap: 60 min for flat/losing trades (extended from 30 —
        # momentum-death above kills dead weight before this fires).
        if not stage1_done and elapsed_minutes >= EARLY_TIMEBOX_MIN:
            return True, (
                f"time_cap_loser_{EARLY_TIMEBOX_MIN}m "
                f"(held={elapsed_minutes:.1f}min — no momentum, killing theta)"
            )

        if stage1_done and elapsed_minutes >= self.ORB_TIME_BOX_WINNER:
            return True, f"time_cap_winner_90m (held={elapsed_minutes:.1f}min)"

        return False, "hold"

    def should_exit(
        self,
        entry_price: float,
        current_price: float,
        entry_time: Optional[datetime] = None,
        now: Optional[datetime] = None,
        stage1_done: bool = False,
        stage1_be_price: Optional[float] = None,
        # Legacy kwargs — kept so old call-sites don't break
        is_last_window: bool = False,
        peak_price: Optional[float] = None,
        struct_stop_price: Optional[float] = None,
        atr_trail_stop: Optional[float] = None,
        trail_armed: bool = False,
        vwap: Optional[float] = None,
        vwap_breached: bool = False,
        trend_dead: bool = False,
        direction: str = "bullish",
        rvol: float = 0.0,
        atr_target_price: Optional[float] = None,
        momentum_fading: bool = False,
    ) -> tuple[bool, str]:
        """Preferred alias for evaluate_exit_conditions — used in position_manager."""
        return self.evaluate_exit_conditions(
            entry_price, current_price,
            entry_time=entry_time, now=now,
            stage1_done=stage1_done, stage1_be_price=stage1_be_price,
            peak_price=peak_price,
            struct_stop_price=struct_stop_price,
            atr_trail_stop=atr_trail_stop,
            trail_armed=trail_armed,
            vwap=vwap,
            vwap_breached=vwap_breached,
            trend_dead=trend_dead,
            direction=direction,
            rvol=rvol,
            atr_target_price=atr_target_price,
            momentum_fading=momentum_fading,
        )
