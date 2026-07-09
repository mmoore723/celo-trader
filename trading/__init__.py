# trading/ — trading logic split into focused job modules.
#   state.py          — LIVE_STATE, per-user state, reset_session_state
#   loop.py           — run_trading_loop, stop_loop
#   entry.py          — ticker/contract selection, tick logic
#   position_manager  — open position management, exits
#   controls.py       — panic_close_all, manual_close, close_trade_by_id
#   diagnostics.py    — ghost position checks, bar thinking logs
