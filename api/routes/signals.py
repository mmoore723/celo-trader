"""
api/routes/signals.py — read-only endpoints over signal_journal.

Added 2026-07-24 per explicit user request: "we need to refactor bot
thinking... lets discuss how to make it useful." bot.log is an unstructured
50MB/day dump and ai_reasoning_log only narrates realized entries/exits —
neither answers "why didn't the bot trade today." signal_journal (see
signal_journal.py) records every strategy signal's final outcome, entered
or blocked-with-reason, and these three endpoints back the Thinking panel's
new summary bar, filterable row list, and 7-day trend strip.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query

router = APIRouter(prefix="/api/signals", tags=["signals"])
logger = logging.getLogger("celo_trader.api.signals")


@router.get("/journal")
def get_journal(
    ticker: str | None = None,
    strategy: str | None = Query(None, description="e.g. VWAP_PB, TREND_CONT"),
    reason: str | None = Query(None, description="reason_code — see signal_journal.REASON_CODES"),
    limit: int = Query(200, ge=1, le=1000),
) -> dict:
    """Today's rows (ET calendar day), newest first, optionally filtered."""
    from signal_journal import get_todays_rows
    try:
        rows = get_todays_rows(ticker=ticker, strategy=strategy, reason=reason, limit=limit)
        return {"entries": rows, "count": len(rows)}
    except Exception as e:
        logger.exception("signal journal fetch failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/journal/summary")
def get_journal_summary() -> dict:
    """
    Today's breakdown: total signals, entered count, and a count per
    reason_code — backs the panel's top summary bar.
    """
    from signal_journal import get_todays_summary
    try:
        return get_todays_summary()
    except Exception as e:
        logger.exception("signal journal summary fetch failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/journal/trend")
def get_journal_trend(
    reason: str = Query(..., description="reason_code to trend — see signal_journal.REASON_CODES"),
    days: int = Query(7, ge=1, le=30),
) -> dict:
    """Daily count of one reason_code over the trailing N days."""
    from signal_journal import get_trend
    try:
        points = get_trend(reason_code=reason, days=days)
        return {"reason": reason, "days": days, "points": points}
    except Exception as e:
        logger.exception("signal journal trend fetch failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/journal/reasons")
def get_reason_codes() -> dict:
    """Reference list of reason codes + human-readable labels, for the filter dropdown."""
    from signal_journal import REASON_CODES
    return {"reasons": REASON_CODES}


def resolve_watching_contracts(watched: list[dict]) -> list[dict]:
    """
    Given watched entries (ticker, direction, or_boundary, phase,
    breakout_bar, retest_bar), resolve each one's real contract — strike,
    expiration, live bid/ask — via select_contract(), the SAME function
    trading/entry.py calls for a real entry, so this shows what would
    actually be bought right now, not a guess.

    Shared by /api/signals/watching and /api/tickers/board (see
    api/routes/tickers.py) so both surfaces resolve the identical contract
    for the identical ticker from one implementation — two copies of this
    logic is exactly the kind of drift that caused the earlier IEX-volume
    bug (see market_data.py's docstring), just in a new place.
    """
    if not watched:
        return []
    from broker import get_clients
    from trading.entry import select_contract
    from config import get_settings

    alpaca, tradier = get_clients()
    settings = get_settings()

    try:
        acct = alpaca.get_account()
        balance = float(acct.get("equity", 0)) if acct else 0.0
    except Exception:
        balance = 0.0
    if balance <= 0:
        balance = float(settings.get("last_known_balance", 0) or 0)

    cap_pct = settings.get("max_position_dollars_pct")
    if cap_pct:
        max_spend = balance * (float(cap_pct) / 100.0)
    else:
        max_spend = float(settings.get("max_position_dollars", 750.0))

    out = []
    for w in watched:
        ticker    = w["ticker"]
        direction = w.get("direction")

        current_price = 0.0
        try:
            quote = alpaca.get_latest_quote(ticker)
            if quote:
                current_price = (float(quote.get("ap", 0) or 0) + float(quote.get("bp", 0) or 0)) / 2
        except Exception:
            pass

        contract = None
        if current_price > 0 and direction and max_spend > 0:
            try:
                # for_display=True — this is a price refresh for the watching
                # card, not a real entry attempt. See select_contract()'s
                # docstring for the incident this prevents.
                contract, _info = select_contract(tradier, ticker, direction, current_price, max_spend, for_display=True)
            except Exception as ex:
                logger.debug("resolve_watching_contracts: select_contract failed for %s: %s", ticker, ex)

        out.append({
            **w,
            "current_price": current_price or None,
            "contract": {
                "symbol": contract.get("symbol"),
                "strike": contract.get("strike"),
                "expiry": contract.get("expiry"),
                "bid":    contract.get("bid"),
                "ask":    contract.get("ask"),
            } if contract else None,
        })
    return out


@router.get("/watching")
def get_watching() -> dict:
    """
    Tickers INST_ORB is currently tracking mid-retest — breakout seen,
    waiting for a retest touch or bounce confirmation before it would enter.
    See strategies/inst_orb.py's module docstring for the Phase 1-3 state
    machine. This is the only strategy in this codebase with an explicit
    multi-bar "waiting" state; every other strategy either fires on the
    current bar or doesn't, so there's nothing to watch for them yet.
    """
    from datetime import date as _date
    import strategies.inst_orb as _inst_orb

    today_iso = _date.today().isoformat()
    watched = [
        {"ticker": k[0], **v}
        for k, v in _inst_orb._retest_state.items()
        if k[1] == today_iso and v.get("phase") in ("breakout_seen", "retesting")
    ]

    # Setups that were mid-retest a moment ago and then gave up (bounce
    # failed, a gate blocked it, etc.) — shown briefly as "expired" instead
    # of just vanishing with no explanation. See _recent_expirations in
    # strategies/inst_orb.py. Excludes anything that's back in `watched`
    # above (a new breakout cycle started again for the same ticker/day).
    watched_tickers = {w["ticker"] for w in watched}
    expired = [
        {"ticker": k[0], **v}
        for k, v in _inst_orb._recent_expirations.items()
        if k[1] == today_iso and k[0] not in watched_tickers
    ]

    if not watched and not expired:
        return {"watching": []}

    try:
        resolved = resolve_watching_contracts(watched)
    except Exception as e:
        logger.exception("watching: resolve_watching_contracts failed")
        raise HTTPException(status_code=500, detail=str(e))

    out = []
    for w in resolved:
        phase = w.get("phase")
        out.append({
            "ticker":        w["ticker"],
            "strategy":      "INST_ORB",
            "direction":     w.get("direction"),
            "option_type":   "call" if w.get("direction") == "bullish" else "put" if w.get("direction") == "bearish" else None,
            "phase":         phase,
            "phase_label":   "1 of 3 — breakout seen" if phase == "breakout_seen" else "2 of 3 — retesting",
            "retest_level":  w.get("or_boundary"),
            "current_price": w.get("current_price"),
            "breakout_time": str(w.get("breakout_bar")) if w.get("breakout_bar") is not None else None,
            "retest_time":   str(w.get("retest_bar")) if w.get("retest_bar") is not None else None,
            "contract":      w.get("contract"),
        })

    for e in expired:
        out.append({
            "ticker":        e["ticker"],
            "strategy":      "INST_ORB",
            "direction":     None,
            "option_type":   None,
            "phase":         "expired",
            "phase_label":   f"expired — was {'1 of 3' if e.get('last_phase') == 'breakout_seen' else '2 of 3'}",
            "retest_level":  None,
            "current_price": None,
            "breakout_time": None,
            "retest_time":   None,
            "contract":      None,
        })

    return {"watching": out}
