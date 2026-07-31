"""
signal_journal.py — Structured "why did/didn't the bot trade" log.

Built 2026-07-24 per explicit user request: bot.log is a 50MB/day unstructured
dump, and the existing ai_reasoning_log (database.py) only narrates REALIZED
entries/exits — it's silent on blocked signals, which is exactly what the user
needed to see (e.g. the BABA 2026-07-24 near-miss: 77%-confidence signal,
cleared every other gate, blocked at the final budget check — invisible in
both bot.log's raw text and ai_reasoning_log's entry/exit-only scope).

This module is the single write path for "what happened to this signal":
  outcome='entered' — the signal became a real trade
  outcome='blocked' — a gate stopped it, with a short reason_code (for
                       aggregation/filtering) and a human-readable reason_detail

Every call is a DUAL WRITE, same pattern as database.py::log_event():
  1. INSERT into the signal_journal table — the persisted, queryable record.
  2. Mirror to bot.log via the structured JSON logger with the same fields in
     extra={}, so the existing live-tail WebSocket (api/routes/ws.py) picks it
     up in real time with badge-ready fields — the Thinking panel updates live
     exactly as it does today, it just now carries structured data too.

Never raises into the trading loop — a journal write failure must never be
allowed to affect a real trade decision (same non-fatal contract as
database.py::log_ai_reasoning()).
"""
from __future__ import annotations

import logging
from typing import Optional

from database import get_conn, _now_et

logger = logging.getLogger("celo_trader.signal_journal")

# Reason codes used across router_gates.py and trading/entry.py. Kept as a
# single reference list here so both call sites (and the frontend filter
# dropdown, via the /api/signals/journal/reasons endpoint) stay in sync.
REASON_CODES = {
    "confidence_floor":      "Confidence below the entry floor",
    "grade_filter":          "Premarket grade below the minimum",
    "conflict_veto":         "Top two signals disagree — market ambiguous",
    "volume_roc_veto":       "Buying/selling pressure already fading",
    "directional_consensus": "3/3 indicators agree the other direction",
    "regime_gate":           "Market regime blocks this direction",
    "macro_vwap_veto":       "Conflicts with SPY/QQQ or ticker's own VWAP posture",
    "budget":                "Cheapest contract costs more than the spend cap",
    "illiquid_contract":     "An affordable contract existed but failed spread/OI filters",
    "no_option_data":        "No usable options chain returned",
    "no_liquid_contracts":   "No contract met spread/open-interest filters",
    "zero_contracts":        "Risk budget too small to size even 1 contract",
    "spread_too_wide":       "Bid-ask spread wider than the spread gate",
    "rr_too_low":            "Reward:risk below the 1.6x minimum",
    "ai_decision_veto":      "AI decision-support layer vetoed or zeroed the size",
}


def log_signal_outcome(
    ticker: str,
    strategy_id: str,
    direction: str,
    confidence: float,
    outcome: str,                          # 'entered' | 'blocked'
    reason_code: Optional[str] = None,     # required when outcome='blocked'
    reason_detail: Optional[str] = None,   # human-readable specifics
) -> None:
    ts = _now_et().isoformat()
    try:
        with get_conn() as conn:
            conn.execute(
                """INSERT INTO signal_journal
                   (ts, ticker, strategy_id, direction, confidence,
                    outcome, reason_code, reason_detail)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (ts, ticker.upper(), strategy_id, direction, round(float(confidence), 4),
                 outcome, reason_code, reason_detail),
            )
    except Exception as exc:
        # Non-fatal by design — see module docstring.
        logger.warning("log_signal_outcome: failed to persist (non-fatal): %s", exc)

    _evt = "SIGNAL_ENTERED" if outcome == "entered" else "SIGNAL_BLOCKED"
    _msg = f"{ticker} {direction} {strategy_id} {confidence:.0%}"
    if reason_detail:
        _msg += f" — {reason_detail}"
    _lvl = logging.INFO
    logger.log(
        _lvl, _msg,
        extra={
            "event":         _evt,
            "ticker":        ticker.upper(),
            "strategy_id":   strategy_id,
            "direction":     direction,
            "confidence":    round(float(confidence), 3),
            "outcome":       outcome,
            "reason_code":   reason_code,
            "reason_detail": reason_detail,
        },
    )


def get_todays_rows(
    ticker: Optional[str] = None,
    strategy: Optional[str] = None,
    reason: Optional[str] = None,
    limit: int = 200,
) -> list[dict]:
    """Today's rows (ET calendar day), newest first, optionally filtered."""
    _today = _now_et().strftime("%Y-%m-%d")
    with get_conn() as conn:
        query = "SELECT * FROM signal_journal WHERE ts LIKE ?"
        params: list = [f"{_today}%"]
        if ticker:
            query += " AND ticker = ?"
            params.append(ticker.upper())
        if strategy:
            query += " AND strategy_id = ?"
            params.append(strategy)
        if reason:
            query += " AND reason_code = ?"
            params.append(reason)
        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]


def get_todays_summary() -> dict:
    """
    Today's breakdown: total signals, entered count, and a count per
    reason_code for every blocked signal — the data behind the panel's
    top summary bar (e.g. "82 signals, 3 entered, confidence floor 62").
    """
    _today = _now_et().strftime("%Y-%m-%d")
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT outcome, reason_code, COUNT(*) as n FROM signal_journal "
            "WHERE ts LIKE ? GROUP BY outcome, reason_code",
            (f"{_today}%",),
        ).fetchall()
    entered = 0
    by_reason: dict[str, int] = {}
    for r in rows:
        if r["outcome"] == "entered":
            entered += r["n"]
        else:
            by_reason[r["reason_code"] or "unknown"] = r["n"]
    total = entered + sum(by_reason.values())
    return {"total": total, "entered": entered, "by_reason": by_reason}


def get_latest_per_ticker_today() -> dict[str, dict]:
    """
    Today's single most recent journal row for every ticker that had at
    least one signal — the "Blocked" status source for the ticker board
    (api/routes/tickers.py). One row per ticker, not the full day's list,
    since the board only needs "what's true right now" per ticker.
    """
    _today = _now_et().strftime("%Y-%m-%d")
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT sj.* FROM signal_journal sj
               INNER JOIN (
                   SELECT ticker, MAX(id) as max_id FROM signal_journal
                   WHERE ts LIKE ? GROUP BY ticker
               ) latest ON sj.ticker = latest.ticker AND sj.id = latest.max_id""",
            (f"{_today}%",),
        ).fetchall()
        return {r["ticker"]: dict(r) for r in rows}


def get_trend(reason_code: str, days: int = 7) -> list[dict]:
    """
    Daily count of one reason_code over the last *days* calendar days —
    the small bar strip that answers "is this gate a today problem or a
    systemic one" without loading a full week of individual rows.
    """
    # Cutoff computed in ET (Python side) rather than SQLite's date('now'),
    # which is UTC — ts is stored as ET isoformat, so a UTC cutoff would
    # misalign by hours right around midnight ET.
    from datetime import timedelta
    _cutoff = (_now_et() - timedelta(days=days)).strftime("%Y-%m-%d")
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT substr(ts, 1, 10) as day, COUNT(*) as n FROM signal_journal "
            "WHERE reason_code = ? AND outcome = 'blocked' AND ts >= ? "
            "GROUP BY day ORDER BY day ASC",
            (reason_code, _cutoff),
        ).fetchall()
        return [{"date": r["day"], "count": r["n"]} for r in rows]
