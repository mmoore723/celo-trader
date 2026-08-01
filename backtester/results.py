"""
backtester/results.py — ResultsMixin: _compute_results, aggregates the
recorded trades into overall/per-strategy/exit-reason summary statistics.

Split out of the old single backtester.py (2026-08-01, file-size cleanup);
no logic changed, only relocated. Combined with the other Backtester*Mixin
classes into Backtester in backtester/engine.py.
"""

import math

import numpy as np


class ResultsMixin:

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
            # Historical option bid/ask, IV and Greeks are not available from
            # the bar feeds used here. This is a comparison tool, not proof of
            # live options profitability.
            "model_fidelity": {
                "exit_mode": "simplified_3_rule" if self.SIMPLIFIED_EXIT_MODE else "full_exit_stack",
                "enabled_strategies": sorted(self.enabled_strategies),
                "settings_snapshot": self.backtest_settings,
                "option_pricing": "synthetic_black_scholes_proxy",
                "limitations": [
                    "No historical option bid/ask or fill data",
                    "Ticker-level IV proxy rather than historical implied volatility",
                    "No historical chain liquidity, Greeks, or spread selection",
                ],
            },
        }
