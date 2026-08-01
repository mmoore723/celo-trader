"""
backtester/simulate.py — SimulateMixin: _simulate_day, the per-day
tick-by-tick replay loop (entry detection via the real strategy router,
exit management via the real risk engine or the simplified 3-rule variant).

Split out of the old single backtester.py (2026-08-01, file-size cleanup);
no logic changed, only relocated. Combined with the other Backtester*Mixin
classes into Backtester in backtester/engine.py.

Kept as ONE function rather than split further: it is a single ordered
per-bar state machine (advance the 5-min exit pointer -> manage an open
position if any -> otherwise evaluate entry signals -> open a position)
built on tightly-coupled local mutable state (in_trade, entry_price,
exit_state, active_strategy, etc.) read and written by many steps across
the loop — the same "irreducible sequential function" exception used for
trading/entry/tick.py's _tick and trading/position_manager/manage.py's
_manage_open_position. Splitting its body would require redesigning its
internal state-passing contract, risking a subtle backtest-fidelity bug
that would then silently propagate into every strategy/threshold decision
made from its results.
"""

from typing import Optional

import pandas as pd

from config import get_trading_windows as _get_trading_windows, STAGE2_TRAIL_PCT
from signals import compute_rvol
from strategy_router import route_signals
from backtest_exit_sim import ExitSimState, evaluate_bt_exit
from backtest_exit_sim_simplified import evaluate_bt_exit_simplified
from backtester.helpers import _get_iv, _estimate_option_price, _simulated_strike, _SIMULATED_DTE


class SimulateMixin:

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
                    "simplified_hard_stop",
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
            # FIX 2026-08-01: was reading tick["atr"] — the 1-minute-resolution
            # entry-detection ATR (14-bar EWM over 1-min bars, ~2-4x smaller
            # than a 5-min-bar ATR for the same underlying since both the
            # lookback window and each bar's own range scale down). This value
            # only feeds initial_atr_stop, which is then checked every 5-min
            # bar against day_df's actual 5-min OHLC extremes (backtest_exit_
            # sim.py) — a stop sized for 1-min noise gets clipped almost
            # immediately by completely normal 5-min bar range, unrelated to
            # whether the trade thesis was right. Live's position_manager.py
            # never has this problem: it recomputes atr fresh from 5-min bars
            # at the first management tick (position_manager.py ~line 534),
            # independent of whatever resolution fed the entry signal. Fixed
            # by reading the matching 5-min day_df bar's atr instead, same
            # source live uses — this only affects the backtest's pre-trail-
            # arm stop; the structural stop and the armed trail were already
            # both correctly 5-min-scale in both paths.
            _atr_at_entry = float(day_df.iloc[idx_5m]["atr"]) if "atr" in day_df.columns and idx_5m >= 0 and pd.notna(day_df.iloc[idx_5m].get("atr")) else None
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
