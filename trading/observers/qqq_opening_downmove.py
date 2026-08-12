"""QQQ morning-downmove paper observer — no order or position capability.

This is the one configuration that survived the pre-final underlying study:
after a 0.25%+ decline in the first thirty minutes, observe a put quote near
10:00 ET and compare its entry ask with its exit bid near 15:55 ET.  It is an
experiment, not a router strategy.  In particular, this module must never
import any order, entry, sizing, risk, or position-management function.
"""
from __future__ import annotations

import logging
from datetime import time
from typing import Any

from broker import AlpacaClient, TradierClient
from config import MAX_CONTRACT_COST, get_settings
from database import (
    close_due_paper_research_observations,
    get_paper_research_scorecard,
    start_paper_research_observation,
)
from signals import bars_to_df
from trading.state import _now_et

logger = logging.getLogger("celo_trader.research")

STUDY_ID = "QQQ_OPENING_DOWNMOVE_PUT_CLOSE_V1"
TICKER = "QQQ"
MIN_OPENING_DOWNMOVE = 0.0025
ENTRY_WINDOW = (time(10, 0), time(10, 4))
EXIT_WINDOW = (time(15, 55), time(15, 59))


def _in_window(now_time: time, window: tuple[time, time]) -> bool:
    return window[0] <= now_time <= window[1]


def _session_frame(alpaca: AlpacaClient):
    bars, is_error, _ = alpaca.get_session_bars(TICKER, "1Min")
    if is_error or not bars:
        return None
    return bars_to_df(bars)


def _latest_underlying_price(alpaca: AlpacaClient, frame: Any) -> float | None:
    try:
        quote = alpaca.get_latest_quote(TICKER)
        bid, ask = float(quote.get("bp", 0) or 0), float(quote.get("ap", 0) or 0)
        if bid > 0 and ask > 0:
            return round((bid + ask) / 2, 6)
    except Exception:
        pass
    try:
        value = float(frame["close"].iloc[-1])
        return value if value > 0 else None
    except Exception:
        return None


def _try_start(alpaca: AlpacaClient, tradier: TradierClient, now) -> None:
    frame = _session_frame(alpaca)
    if frame is None or frame.empty:
        return
    today = now.date()
    opening = frame[(frame["time"].dt.date == today) & (frame["time"].dt.time >= time(9, 30)) &
                    (frame["time"].dt.time <= time(9, 59))]
    entry_rows = frame[(frame["time"].dt.date == today) & (frame["time"].dt.time == time(10, 0))]
    if len(opening) < 30 or entry_rows.empty:
        return
    opening_move = (float(opening["close"].iloc[-1]) - float(opening["open"].iloc[0])) / float(opening["open"].iloc[0])
    if opening_move > -MIN_OPENING_DOWNMOVE:
        return
    entry_price = float(entry_rows["open"].iloc[0])
    # Reuse the existing *display* selector: it only reads a chain, applies
    # the same liquid 7–21 DTE contract policy, and cannot submit an order.
    try:
        from trading.entry.contract import select_contract
        contract, selection = select_contract(
            tradier, TICKER, "bearish", entry_price, MAX_CONTRACT_COST * 100, for_display=True,
        )
    except Exception:
        contract, selection = None, {"reason": "selector_error"}
    settings = get_settings()
    created = start_paper_research_observation(
        study_id=STUDY_ID, observed_at=now, ticker=TICKER, direction="bearish",
        underlying_entry_price=entry_price, contract=contract,
        broker_account_id=settings.get("active_broker_account_id") or None,
        metadata={
            "study_kind": "paper_observation_only", "entry_reference": "10:00 ET underlying open",
            "exit_reference": "near 15:55 ET observed quote", "opening_move_pct": round(opening_move * 100, 4),
            "minimum_opening_downmove_pct": MIN_OPENING_DOWNMOVE * 100,
            "contract_selection": selection.get("reason"), "quote_execution_assumption": "buy entry ask; sell exit bid",
        },
    )
    if created:
        logger.info("QQQ paper research observation started; contract=%s", (contract or {}).get("symbol") or "unavailable")


def _try_close(alpaca: AlpacaClient, tradier: TradierClient, now) -> None:
    frame = _session_frame(alpaca)
    if frame is None or frame.empty:
        return
    price = _latest_underlying_price(alpaca, frame)
    if price is None:
        return
    settings = get_settings()
    closed = close_due_paper_research_observations(
        study_id=STUDY_ID, observed_at=now, ticker=TICKER, underlying_exit_price=price,
        broker_account_id=settings.get("active_broker_account_id") or None,
        quote_lookup=tradier.get_option_quote,
    )
    if closed:
        logger.info("QQQ paper research observation closed; rows=%s", closed)


def maybe_observe(alpaca: AlpacaClient, tradier: TradierClient) -> None:
    """Observe only inside two narrow market windows and only in paper mode."""
    settings = get_settings()
    if not bool(settings.get("paper_trading", True)) or not bool(settings.get("qqq_opening_research_enabled", True)):
        return
    now = _now_et()
    if now.weekday() >= 5:
        return
    try:
        if _in_window(now.time(), ENTRY_WINDOW):
            _try_start(alpaca, tradier, now)
        elif _in_window(now.time(), EXIT_WINDOW):
            _try_close(alpaca, tradier, now)
    except Exception:
        # A research record must never interrupt or alter the normal bot loop.
        logger.warning("QQQ paper research observer failed (non-fatal)", exc_info=True)


def scorecard() -> dict:
    """Read-only snapshot for the API/dashboard."""
    settings = get_settings()
    return get_paper_research_scorecard(
        study_id=STUDY_ID, broker_account_id=settings.get("active_broker_account_id") or None,
    )
