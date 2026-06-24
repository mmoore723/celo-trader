"""
trading_logic.py — Public face (thin re-export layer).

The implementation has been refactored into trading/ with five focused modules:

  trading/state.py            — LIVE_STATE, _now_et(), reset_session_state()
  trading/loop.py             — run_trading_loop, stop_loop
  trading/entry.py            — select_ticker, select_contract, _tick
  trading/position_manager.py — _manage_open_position, _close_position
  trading/diagnostics.py      — _log_bar_thinking, _check_ghost_positions
  trading/controls.py         — panic_close_all, manual_close_position,
                                 close_trade_by_id

All public symbols are re-exported here so that dashboard.py, main.py, and
any systemd / process-supervisor imports continue to work without changes.
"""

# ── Shared state ──────────────────────────────────────────────────────────────
from trading.state import (
    LIVE_STATE,
    reset_session_state,
    _now_et,
    _ET_TZ,
    _stop_event,
    _bot_loop_lock,
    _BOT_ROOT,
    _DATA_GAP_WARN_MINUTES,
    _DATA_GAP_PAUSE_MINUTES,
    _update_data_gap,
)

# ── Loop lifecycle ─────────────────────────────────────────────────────────────
from trading.loop import (
    run_trading_loop,
    stop_loop,
    _run_trading_loop_inner,
    _sleep_until_next_day,
)

# ── Entry / tick ───────────────────────────────────────────────────────────────
from trading.entry import (
    select_ticker,
    select_contract,
    _tick,
)

# ── Position management ────────────────────────────────────────────────────────
from trading.position_manager import (
    _manage_open_position,
    _close_position,
)

# ── Diagnostics ───────────────────────────────────────────────────────────────
from trading.diagnostics import (
    _log_bar_thinking,
    _check_ghost_positions,
    _sweep_orphaned_orders,
)

# ── Controls ──────────────────────────────────────────────────────────────────
from trading.controls import (
    panic_close_all,
    manual_close_position,
    close_trade_by_id,
    _panic_close_all_positions,
)

__all__ = [
    # state
    "LIVE_STATE", "reset_session_state", "_now_et", "_ET_TZ",
    "_stop_event", "_bot_loop_lock", "_BOT_ROOT",
    "_DATA_GAP_WARN_MINUTES", "_DATA_GAP_PAUSE_MINUTES", "_update_data_gap",
    # loop
    "run_trading_loop", "stop_loop",
    "_run_trading_loop_inner", "_sleep_until_next_day",
    # entry
    "select_ticker", "select_contract", "_tick",
    # position_manager
    "_manage_open_position", "_close_position",
    # diagnostics
    "_log_bar_thinking", "_check_ghost_positions", "_sweep_orphaned_orders",
    # controls
    "panic_close_all", "manual_close_position", "close_trade_by_id",
    "_panic_close_all_positions",
]
