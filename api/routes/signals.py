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
import json
from collections import Counter

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


def _json_object(value: object) -> dict:
    """Return an object from legacy/malformed JSON without breaking the audit UI."""
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        parsed = json.loads(str(value))
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}


@router.get("/opportunities")
def get_scanner_opportunities(
    date: str | None = Query(None, description="ET calendar date, YYYY-MM-DD"),
    ticker: str | None = None,
    strategy: str | None = None,
    outcome: str | None = Query(None, description="pending | blocked | observed_only | entered"),
    limit: int = Query(500, ge=1, le=1000),
) -> dict:
    """A day-by-day audit of every scanner candidate the router evaluated.

    This deliberately starts with ``shadow_candidates`` rather than the trade
    journal.  A trade journal can only show orders; this page must also retain
    the candidates the scanner saw but a gate stopped.  Contract, quantity,
    and exit-plan details are included only when the entry path actually
    reached those decisions.  No contract is invented for early gate rejects.
    """
    from config import get_settings
    from database import get_conn, _now_et

    selected_date = (date or _now_et().date().isoformat()).strip()
    # Keep the date input constrained to the stored ISO calendar shape.  This
    # also prevents passing a broad SQL pattern through this read-only filter.
    if len(selected_date) != 10 or selected_date[4] != "-" or selected_date[7] != "-":
        raise HTTPException(status_code=422, detail="date must use YYYY-MM-DD")

    account_id = get_settings().get("active_broker_account_id") or None
    clauses = ["sc.observed_at LIKE ?"]
    params: list[object] = [f"{selected_date}%"]
    if account_id:
        clauses.append("sc.broker_account_id = ?")
        params.append(account_id)
    else:
        # Keep legacy data separate too.  Falling back to every row here would
        # silently blend scanner history from different broker identities.
        clauses.append("(sc.broker_account_id IS NULL OR sc.broker_account_id = '')")
    if ticker:
        clauses.append("sc.ticker = ?")
        params.append(ticker.upper())
    if strategy:
        clauses.append("sc.strategy_id = ?")
        params.append(strategy)
    if outcome:
        clauses.append("sc.final_outcome = ?")
        params.append(outcome)

    where = " AND ".join(clauses)
    try:
        with get_conn() as conn:
            candidate_rows = conn.execute(
                "SELECT sc.*, t.ticker AS trade_ticker, t.contract_symbol, t.option_type, "
                "t.strike, t.expiry, t.contracts, t.entry_price, t.exit_price, "
                "t.status AS trade_status, t.entry_time, t.exit_time, t.exit_reason, t.realized_pnl "
                "FROM shadow_candidates sc LEFT JOIN trades t ON t.id = sc.linked_trade_id "
                f"WHERE {where} ORDER BY sc.observed_at DESC LIMIT ?",
                tuple(params + [limit]),
            ).fetchall()
            # The journal is the durable home for the enriched decision
            # context.  A candidate ID in strategy_meta is an explicit join,
            # never a fuzzy same-minute match that could join two setups.
            journal_where = ["ts LIKE ?"]
            journal_params: list[object] = [f"{selected_date}%"]
            if account_id:
                journal_where.append("broker_account_id = ?")
                journal_params.append(account_id)
            else:
                # A database created before account identities existed may
                # still have legacy rows.  Only surface those when there is
                # no active identity to protect, never alongside a new key.
                journal_where.append("(broker_account_id IS NULL OR broker_account_id = '')")
            journal_rows = conn.execute(
                "SELECT * FROM signal_journal WHERE " + " AND ".join(journal_where) + " ORDER BY id DESC",
                tuple(journal_params),
            ).fetchall()
            date_rows = conn.execute(
                "SELECT DISTINCT substr(observed_at, 1, 10) AS day FROM shadow_candidates "
                + ("WHERE broker_account_id = ? " if account_id else "WHERE (broker_account_id IS NULL OR broker_account_id = '') ")
                + "ORDER BY day DESC LIMIT 90",
                (account_id,) if account_id else (),
            ).fetchall()
    except Exception as exc:
        logger.exception("scanner opportunities query failed")
        raise HTTPException(status_code=500, detail=str(exc))

    journal_by_candidate: dict[str, dict] = {}
    orphan_journal: list[dict] = []
    for raw in journal_rows:
        row = dict(raw)
        context = _json_object(row.get("context_json"))
        meta = context.get("strategy_meta") if isinstance(context.get("strategy_meta"), dict) else {}
        candidate_id = meta.get("shadow_candidate_id")
        if candidate_id:
            journal_by_candidate.setdefault(str(candidate_id), {**row, "_context": context})
        else:
            orphan_journal.append({**row, "_context": context})

    entries: list[dict] = []
    for raw in candidate_rows:
        row = dict(raw)
        candidate_id = str(row["candidate_id"])
        journal = journal_by_candidate.get(candidate_id)
        context = journal.get("_context", {}) if journal else {}
        metadata = _json_object(row.get("metadata_json"))
        # Decision-time context is preferred because it contains the selected
        # contract if entry evaluation reached it.  Raw metadata remains the
        # fallback for observed-only candidates.
        contract = context.get("contract") if isinstance(context.get("contract"), dict) else {}
        entry_plan = context.get("entry_plan") if isinstance(context.get("entry_plan"), dict) else {}
        exit_plan = context.get("exit_plan") if isinstance(context.get("exit_plan"), dict) else {}
        if not entry_plan:
            entry_plan = {"trigger": metadata.get("entry_trigger") or "Scanner setup detected"}
        outcome_value = str(row.get("final_outcome") or "pending")
        reason_code = row.get("gate_reason") or (journal.get("reason_code") if journal else None)
        reason_detail = row.get("gate_detail") or (journal.get("reason_detail") if journal else None)
        trade = None
        if row.get("linked_trade_id"):
            trade = {
                "id": row.get("linked_trade_id"), "contract_symbol": row.get("contract_symbol"),
                "option_type": row.get("option_type"), "strike": row.get("strike"),
                "expiry": row.get("expiry"), "contracts": row.get("contracts"),
                "entry_price": row.get("entry_price"), "exit_price": row.get("exit_price"),
                "status": row.get("trade_status"), "entry_time": row.get("entry_time"),
                "exit_time": row.get("exit_time"), "exit_reason": row.get("exit_reason"),
                "pnl": row.get("realized_pnl"),
            }
        entries.append({
            "id": candidate_id, "source": "candidate", "observed_at": row.get("observed_at"),
            "ticker": row.get("ticker"), "strategy_id": row.get("strategy_id"),
            "direction": row.get("direction"), "confidence": row.get("confidence"),
            "tier": row.get("tier"), "trigger_bar": row.get("trigger_bar"),
            "outcome": outcome_value, "reason_code": reason_code, "reason_detail": reason_detail,
            "entry_plan": entry_plan, "contract": contract,
            "planned_quantity": context.get("planned_quantity"), "exit_plan": exit_plan,
            "underlying_entry_price": row.get("underlying_entry_price"),
            "underlying_exit_price": row.get("underlying_exit_price"),
            "directional_move_pct": row.get("directional_move_pct"),
            "direction_correct": row.get("direction_correct"),
            "outcome_observed_at": row.get("outcome_observed_at"), "trade": trade,
        })

    # Pre-link historical journal rows are still worth displaying.  Clearly
    # label them as journal-only: they do not have a candidate outcome or a
    # virtual fill behind them, so a learner will not mistake them for one.
    candidate_ids_in_page = {str(dict(row)["candidate_id"]) for row in candidate_rows}
    for journal in orphan_journal:
        context = journal.get("_context", {})
        meta = context.get("strategy_meta") if isinstance(context.get("strategy_meta"), dict) else {}
        if str(meta.get("shadow_candidate_id") or "") in candidate_ids_in_page:
            continue
        if ticker and journal.get("ticker") != ticker.upper():
            continue
        if strategy and journal.get("strategy_id") != strategy:
            continue
        if outcome and journal.get("outcome") != outcome:
            continue
        entries.append({
            "id": f"journal-{journal.get('id')}", "source": "journal_only", "observed_at": journal.get("ts"),
            "ticker": journal.get("ticker"), "strategy_id": journal.get("strategy_id"),
            "direction": journal.get("direction"), "confidence": journal.get("confidence"),
            "tier": journal.get("tier") or "main", "trigger_bar": context.get("trigger_bar"),
            "outcome": journal.get("outcome"), "reason_code": journal.get("reason_code"),
            "reason_detail": journal.get("reason_detail"),
            "entry_plan": context.get("entry_plan") if isinstance(context.get("entry_plan"), dict) else {},
            "contract": context.get("contract") if isinstance(context.get("contract"), dict) else {},
            "planned_quantity": context.get("planned_quantity"),
            "exit_plan": context.get("exit_plan") if isinstance(context.get("exit_plan"), dict) else {},
            "underlying_entry_price": None, "underlying_exit_price": None,
            "directional_move_pct": None, "direction_correct": None,
            "outcome_observed_at": None,
            "trade": {"id": journal.get("trade_id")} if journal.get("trade_id") else None,
        })
    entries.sort(key=lambda entry: str(entry.get("observed_at") or ""), reverse=True)
    entries = entries[:limit]
    counts = Counter(str(entry.get("outcome") or "pending") for entry in entries)
    return {
        "date": selected_date, "account_scoped": bool(account_id),
        "available_dates": [str(row["day"]) for row in date_rows if row["day"]],
        "summary": {"total": len(entries), **counts},
        "note": "A scanner opportunity is not an order. Contract, quantity, and exit plan appear only after the bot actually reached that decision. The later result is the underlying's 60-minute directional move, not pretend option P&L.",
        "entries": entries,
    }


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
