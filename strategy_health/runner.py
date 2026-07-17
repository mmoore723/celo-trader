"""
strategy_health/runner.py — orchestrates one full strategy health audit:
run the engine per ticker, aggregate per strategy, cross-reference actual
DB trades for that day, generate both narratives, save the result.

Called automatically once/day from trading/loop.py (after-hours transition)
and on-demand from api/routes/strategy_health.py.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Optional

from broker import AlpacaClient
from database import get_conn, save_strategy_audit
from strategy_health.engine import audit_ticker
from strategy_health.narrator import build_narrative
from strategy_health.ai_narrator import build_ai_narrative

logger = logging.getLogger("celo_trader.strategy_health.runner")

DEFAULT_TICKERS = ["SPY", "QQQ", "NVDA", "AAPL", "TSLA", "AMD", "META", "AMZN"]


def _recent_traded_tickers(days: int = 5) -> list[str]:
    """Tickers actually traded in the last N days — more relevant than a
    fixed list if the scanner has been rotating through different names."""
    try:
        with get_conn() as conn:
            rows = conn.execute(
                "SELECT DISTINCT ticker FROM trades "
                "WHERE entry_time >= datetime('now', ?) ORDER BY entry_time DESC",
                (f"-{days} days",),
            ).fetchall()
        tickers = [r["ticker"] for r in rows if r["ticker"]]
        return tickers[:10] if tickers else []
    except Exception as exc:
        logger.warning("strategy_health: could not read recent tickers: %s", exc)
        return []


def _actual_trades_for(date_str: str, ticker: str, strategy_id: str) -> dict:
    """Real closed-trade outcomes for one ticker/strategy on one date, from
    whichever DB (paper/live) is currently active — the ground truth."""
    try:
        with get_conn() as conn:
            rows = conn.execute(
                "SELECT realized_pnl FROM trades WHERE status='closed' "
                "AND ticker=? AND strategy_id=? AND substr(exit_time,1,10)=?",
                (ticker, strategy_id, date_str),
            ).fetchall()
        pnls = [float(r["realized_pnl"]) for r in rows if r["realized_pnl"] is not None]
        return {
            "actual_trades": len(pnls),
            "actual_wins":   sum(1 for p in pnls if p > 0),
            "actual_pnl":    round(sum(pnls), 2),
        }
    except Exception as exc:
        logger.warning("strategy_health: trade cross-ref failed for %s/%s: %s",
                        ticker, strategy_id, exc)
        return {"actual_trades": 0, "actual_wins": 0, "actual_pnl": 0.0}


def run_daily_audit(alpaca: Optional[AlpacaClient] = None,
                     tickers: Optional[list[str]] = None) -> dict:
    """
    Run the full audit and persist it. Returns the aggregate dict that was
    saved (same shape narrator.build_narrative() expects).
    """
    if alpaca is None:
        alpaca = AlpacaClient()
    if tickers is None:
        tickers = _recent_traded_tickers() or DEFAULT_TICKERS

    per_strategy: dict = defaultdict(lambda: {
        "raw_signals": 0, "router_survivors": 0,
        "worked_raw": 0, "worked_survivors": 0,
        "actual_trades": 0, "actual_wins": 0, "actual_pnl": 0.0,
    })
    scanned: list[str] = []
    audit_date: Optional[str] = None

    for ticker in tickers:
        try:
            result = audit_ticker(alpaca, ticker)
        except Exception as exc:
            logger.warning("strategy_health: audit_ticker failed for %s: %s", ticker, exc)
            continue
        if result is None:
            continue

        scanned.append(ticker)
        audit_date = result["date"]   # same trading day for every ticker (most recent close)

        for strategy_id, row in result["per_strategy"].items():
            agg = per_strategy[strategy_id]
            agg["raw_signals"]      += row["raw_signals"]
            agg["router_survivors"] += row["router_survivors"]
            agg["worked_raw"]       += row["worked_raw"]
            agg["worked_survivors"] += row["worked_survivors"]

            trade_stats = _actual_trades_for(result["date"], ticker, strategy_id)
            agg["actual_trades"] += trade_stats["actual_trades"]
            agg["actual_wins"]   += trade_stats["actual_wins"]
            agg["actual_pnl"]    += trade_stats["actual_pnl"]

    aggregate = {
        "date":            audit_date or "unknown",
        "tickers_scanned": scanned,
        "per_strategy":    dict(per_strategy),
    }

    rule_summary = build_narrative(aggregate)
    ai_summary   = build_ai_narrative(aggregate)   # None if no API key / call failed

    try:
        save_strategy_audit({
            "audit_date":   aggregate["date"],
            "tickers":      ",".join(scanned),
            "aggregate":    aggregate,
            "rule_summary": rule_summary,
            "ai_summary":   ai_summary,
        })
    except Exception as exc:
        logger.error("strategy_health: failed to save audit: %s", exc)

    logger.info("strategy_health: audit complete for %s (%d ticker(s), %d strategies)",
                aggregate["date"], len(scanned), len(per_strategy))

    aggregate["rule_summary"] = rule_summary
    aggregate["ai_summary"]   = ai_summary
    return aggregate
