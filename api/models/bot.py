"""
api/models/bot.py — Bot status / action response schemas.

Split out of the old single api/models.py (2026-08-01, file-size cleanup);
no logic changed, only relocated.
"""
from __future__ import annotations
from typing import Optional
from pydantic import BaseModel


class BotStatus(BaseModel):
    running: bool
    mode: str                        # "live" | "sim" | "stopped"
    ticker: Optional[str]
    account_balance: float
    day_start_balance: float         # Alpaca equity captured once at bot startup — never derived
    session_pnl: float
    options_buying_power: float
    last_update: Optional[str]
    network_ok: bool
    last_strategy_id: Optional[str]
    current_stop_pct: Optional[float]
    last_signal: Optional[str]
    ghost_position_detected: bool
    is_paper: bool = True            # True = paper-trading, False = live account
    # ── Contract eval snapshot (written by entry.py after each signal eval) ────
    last_eval_strike: Optional[float] = None
    last_eval_expiry: Optional[str]   = None
    last_eval_contract_symbol: Optional[str] = None
    last_eval_eff_entry: Optional[float] = None
    last_eval_contracts: Optional[int] = None
    last_eval_opt_type: Optional[str] = None
    last_eval_ticker: Optional[str] = None
    # FIX 2026-07-28: entry.py has always written a full last-10 evaluation
    # history to bot_state.json's "eval_log" key (see trading/entry.py
    # ~line 1321), but this field never existed on BotStatus — FastAPI's
    # response_model silently strips any key not declared on the model, so
    # the frontend's "Signal History" panel has been permanently empty
    # (status?.eval_log was always undefined) regardless of real activity.
    eval_log: list[dict] = []
    # FIX 2026-07-31: same bug class as eval_log above — position_manager.py
    # has always written a live per-position dict (current_option_price,
    # current_option_price_time, contracts) keyed by trade id to
    # bot_state.json's "open_positions" key, but this field never existed on
    # BotStatus either. The Open Positions table's "Now" and "P&L (live)"
    # columns (LiveTrading.tsx: status?.open_positions?.[id]) have been
    # silently reading undefined this whole time and rendering "—".
    open_positions: dict = {}
    # 2026-07-31: surfaces broker_health.py's rolling error tracker so a
    # sustained Tradier/Alpaca outage shows a visible banner instead of
    # silently blocking every signal one ticker at a time (see the incident
    # that motivated this: a masked credential overwrote the real Tradier
    # key, causing 268 silent 401s across every ticker with zero indication
    # anywhere except individual "no_option_data" journal rows).
    broker_alerts: list[dict] = []
    # Present only while the paper-only opportunity scheduler is comparing
    # lower-confidence candidates before it is allowed to create an order.
    opportunity_window: dict = {}
    # Maintenance mode — set by admin to halt all trading and show maintenance screen
    maintenance_mode: bool = False
    maintenance_message: str = ""


class BotActionResponse(BaseModel):
    ok: bool
    message: str
