"""
api/routes/tickers.py — GET /api/tickers/board: one row per ticker, current
state only.

Built 2026-07-31 per explicit user request: the old page had three separate
places to check a ticker's status (Open Positions table, the INST_ORB-only
Watching tab, and the Thinking panel's scrolling per-signal journal), which
could each be looking at slightly different data and drift out of sync. This
endpoint reads the SAME underlying sources those three surfaces already use
— it doesn't recompute anything — and merges them into one row per ticker so
the frontend has a single place to render instead of three.

Priority per ticker: trading > watching > blocked. A ticker gets exactly one
row. If it's an open position, that's the only fact that matters right now —
an earlier confidence-floor block from before entry is stale information.
"""
from __future__ import annotations

import logging
from datetime import date as _date

from fastapi import APIRouter, HTTPException, Request

router = APIRouter(prefix="/api/tickers", tags=["tickers"])
logger = logging.getLogger("celo_trader.api.tickers")


def _get_uid(request: Request) -> str:
    return getattr(request.state, "user_id", "admin")


@router.get("/board")
def get_board(request: Request) -> dict:
    from database import get_open_trades
    from signal_journal import get_latest_per_ticker_today
    from api.routes.bot import _read_bot_state
    import strategies.inst_orb as _inst_orb

    user_id = _get_uid(request)
    rows: list[dict] = []
    seen: set[str] = set()

    # ── 1. Trading — real open positions, highest priority ─────────────────
    # Live price read from the SAME bot_state.json "open_positions" dict the
    # Open Positions table itself reads (status.open_positions[id]) — this
    # can never disagree with that table because it's the same source.
    try:
        open_trades = get_open_trades() or []
    except Exception:
        logger.exception("board: get_open_trades failed")
        open_trades = []

    state = _read_bot_state(user_id)
    live_positions = state.get("open_positions") or {}

    for t in open_trades:
        ticker = (t.get("ticker") or "").upper()
        if not ticker or ticker in seen:
            continue
        seen.add(ticker)
        live     = live_positions.get(str(t.get("id"))) or {}
        cur_px   = live.get("current_option_price")
        qty      = live.get("contracts") or t.get("contracts") or 1
        entry_px = float(t.get("entry_price") or 0)
        pnl      = (cur_px - entry_px) * qty * 100 if cur_px is not None else None
        entry_hm = (t.get("entry_time") or "")[11:16]
        rows.append({
            "ticker":        ticker,
            "status":        "trading",
            "strategy":      t.get("strategy_id"),
            "direction":     t.get("option_type"),
            "detail":        f"entered {entry_hm}" if entry_hm else "entered",
            "time":          t.get("entry_time"),
            "retest_level":  None,
            "contract": {
                "symbol": t.get("contract_symbol"),
                "strike": t.get("strike"),
                "expiry": t.get("expiry"),
            },
            "entry_price":   entry_px,
            "current_price": cur_px,
            "pnl":           round(pnl, 2) if pnl is not None else None,
        })

    # ── 2. Watching — INST_ORB mid-retest. Contract resolution (strike,
    # expiry, live bid/ask, current price) uses the SAME resolver
    # /api/signals/watching calls — see resolve_watching_contracts() in
    # api/routes/signals.py — so this can't show a different contract for
    # the same ticker than that endpoint would. ────────────────────────────
    from api.routes.signals import resolve_watching_contracts

    today_iso = _date.today().isoformat()
    watched_raw = [
        {"ticker": k[0], **v}
        for k, v in _inst_orb._retest_state.items()
        if k[1] == today_iso and k[0] not in seen and v.get("phase") in ("breakout_seen", "retesting")
    ]
    try:
        watched_resolved = resolve_watching_contracts(watched_raw)
    except Exception:
        logger.exception("board: resolve_watching_contracts failed")
        watched_resolved = watched_raw

    for v in watched_resolved:
        ticker = v["ticker"]
        if ticker in seen:
            continue
        seen.add(ticker)
        phase = v.get("phase")
        rows.append({
            "ticker":        ticker,
            "status":        "watching",
            "strategy":      "INST_ORB",
            "direction":     v.get("direction"),
            "detail":        "1 of 3 — breakout seen" if phase == "breakout_seen" else "2 of 3 — retesting",
            "time":          str(v.get("retest_bar") or v.get("breakout_bar") or "") or None,
            "retest_level":  v.get("or_boundary"),
            "contract":      v.get("contract"),
            "entry_price":   None,
            "current_price": v.get("current_price"),
            "pnl":           None,
        })

    for k, v in _inst_orb._recent_expirations.items():
        ticker = k[0]
        if k[1] != today_iso or ticker in seen:
            continue
        seen.add(ticker)
        was = "1 of 3" if v.get("last_phase") == "breakout_seen" else "2 of 3"
        rows.append({
            "ticker":        ticker,
            "status":        "watching",
            "strategy":      "INST_ORB",
            "direction":     None,
            "detail":        f"expired — was {was}",
            "time":          None,
            "retest_level":  None,
            "contract":      None,
            "entry_price":   None,
            "current_price": None,
            "pnl":           None,
        })

    # ── 3. Blocked — latest journal row per ticker today, entered rows
    # skipped (either already in `seen` above, or the position already
    # closed today — not "blocked", just not currently anything) ──────────
    try:
        latest = get_latest_per_ticker_today()
    except Exception:
        logger.exception("board: get_latest_per_ticker_today failed")
        latest = {}

    for ticker, r in latest.items():
        if ticker in seen or r.get("outcome") != "blocked":
            continue
        seen.add(ticker)
        rows.append({
            "ticker":        ticker,
            "status":        "blocked",
            "strategy":      r.get("strategy_id"),
            "direction":     r.get("direction"),
            "detail":        r.get("reason_detail") or (r.get("reason_code") or "").replace("_", " "),
            "time":          r.get("ts"),
            "reason_code":   r.get("reason_code"),
            "retest_level":  None,
            "contract":      None,
            "entry_price":   None,
            "current_price": None,
            "pnl":           None,
        })

    _order = {"trading": 0, "watching": 1, "blocked": 2}
    rows.sort(key=lambda r: _order.get(r["status"], 3))
    return {"tickers": rows}
