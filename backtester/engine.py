"""
backtester/engine.py — Backtester: assembles the seven Backtester*Mixin
classes into the concrete class used everywhere else in the app, plus the
class-level constants shared across them (mirrored from RiskManager so
sizing/exit math always stays in sync with the live engine).

Split out of the old single backtester.py (2026-08-01, file-size cleanup);
no logic changed, only relocated. self.X resolves via Python's normal method
resolution order regardless of which mixin file defines X, so every existing
call site (bt.run(), bt.SIMPLIFIED_EXIT_MODE = True, etc.) is unaffected.

  helpers.py     — free functions (not part of the class): quiet-logging,
                   IV lookup, option pricer (imported directly by the
                   mixins below that need them, not part of this class)
  core.py        — CoreMixin      (__init__, contract sizing)
  fetch.py       — FetchMixin     (extra-timeframe fetch, entry-source prep)
  market_data.py — MarketDataMixin (cached fetch-and-precompute pipeline)
  run.py         — RunMixin       (run(): the public entry point)
  simulate.py    — SimulateMixin  (_simulate_day: per-day replay loop)
  close.py       — CloseMixin     (_close_bt_trade: trade recorder)
  results.py     — ResultsMixin   (_compute_results: summary stats)
"""

from risk import RiskManager
from backtester.core import CoreMixin
from backtester.fetch import FetchMixin
from backtester.market_data import MarketDataMixin
from backtester.run import RunMixin
from backtester.simulate import SimulateMixin
from backtester.close import CloseMixin
from backtester.results import ResultsMixin


class Backtester(
    CoreMixin, FetchMixin, MarketDataMixin, RunMixin,
    SimulateMixin, CloseMixin, ResultsMixin,
):
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
