#!/usr/bin/env python3
"""Reconcile Tradier candidate quotes with linked Alpaca paper fills.

This is a read-only execution-parity audit, not a simulator.  Each comparison
requires one closed trade linked to one candidate, the exact same option
contract at candidate entry and the strategy's registered 30/90-minute mark,
and internally consistent broker P&L.  The residual is intentionally called a
cross-feed gap rather than slippage: quote timing, market-data differences,
paper-fill modeling, and order execution can all contribute.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sqlite3
from statistics import mean, median
from typing import Any, Iterable

from config.strategy_catalog import REVIEWED_STRATEGIES


def _profit_factor(values: Iterable[float]) -> float | str | None:
    rows = list(values)
    gains = sum(value for value in rows if value > 0)
    losses = -sum(value for value in rows if value < 0)
    if losses <= 0:
        return "inf" if gains > 0 else None
    return round(gains / losses, 4)


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    reference = [float(row["tradier_reference_pnl"]) for row in rows]
    actual = [float(row["alpaca_realized_pnl"]) for row in rows]
    entry_gap = [float(row["entry_cross_feed_adverse_dollars"]) for row in rows]
    exit_gap = [float(row["exit_cross_feed_adverse_dollars"]) for row in rows]
    return {
        "matched_trades": len(rows),
        "trading_days": len({str(row["entry_time"])[:10] for row in rows}),
        "tradier_reference": {
            "net_pnl": round(sum(reference), 2),
            "profit_factor": _profit_factor(reference),
            "wins": sum(value > 0 for value in reference),
            "losses": sum(value < 0 for value in reference),
            "average_pnl": round(mean(reference), 2) if reference else None,
            "median_pnl": round(median(reference), 2) if reference else None,
        },
        "alpaca_paper": {
            "net_pnl": round(sum(actual), 2),
            "profit_factor": _profit_factor(actual),
            "wins": sum(value > 0 for value in actual),
            "losses": sum(value < 0 for value in actual),
            "average_pnl": round(mean(actual), 2) if actual else None,
            "median_pnl": round(median(actual), 2) if actual else None,
        },
        "cross_feed_adverse_dollars": {
            "entry": round(sum(entry_gap), 2),
            "exit": round(sum(exit_gap), 2),
            "total": round(sum(entry_gap) + sum(exit_gap), 2),
        },
    }


def build_report(db_path: Path, *, first_trade_id: int, last_trade_id: int) -> dict[str, Any]:
    if first_trade_id > last_trade_id:
        raise ValueError("first trade id must not exceed last trade id")
    conn = sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    integrity = str(conn.execute("PRAGMA integrity_check").fetchone()[0])
    trades = [dict(row) for row in conn.execute(
        "SELECT * FROM trades WHERE id BETWEEN ? AND ? AND status='closed' ORDER BY entry_time, id",
        (first_trade_id, last_trade_id),
    )]

    matched: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    reason_counts: Counter[str] = Counter()
    for trade in trades:
        trade_id = int(trade["id"])
        candidate_id = str(trade.get("candidate_id") or "")
        reason: str | None = None
        candidate = None
        entry_quote = None
        exit_quote = None
        rule = REVIEWED_STRATEGIES.get(str(trade.get("strategy_id") or ""))
        if not candidate_id:
            reason = "missing_candidate_link"
        elif rule is None or rule.observation_only or rule.exit_minutes is None:
            reason = "strategy_has_no_registered_executable_exit"
        else:
            candidate_row = conn.execute(
                "SELECT * FROM shadow_candidates WHERE candidate_id=?", (candidate_id,),
            ).fetchone()
            candidate = dict(candidate_row) if candidate_row else None
            if candidate is None:
                reason = "candidate_record_missing"
            elif candidate.get("linked_trade_id") not in (None, trade_id):
                reason = "candidate_linked_to_different_trade"
            elif str(candidate.get("strategy_id")) != str(trade.get("strategy_id")):
                reason = "candidate_strategy_mismatch"
            elif str(candidate.get("ticker")).upper() != str(trade.get("ticker")).upper():
                reason = "candidate_ticker_mismatch"
            elif str(trade.get("ticker")).upper() not in rule.tickers:
                reason = "trade_outside_reviewed_ticker_scope"
            else:
                entry_row = conn.execute(
                    "SELECT * FROM candidate_option_quote_observations "
                    "WHERE candidate_id=? AND observation_kind='entry'", (candidate_id,),
                ).fetchone()
                exit_kind = f"mark_{rule.exit_minutes}m"
                exit_row = conn.execute(
                    "SELECT * FROM candidate_option_quote_observations "
                    "WHERE candidate_id=? AND observation_kind=?", (candidate_id, exit_kind),
                ).fetchone()
                entry_quote = dict(entry_row) if entry_row else None
                exit_quote = dict(exit_row) if exit_row else None
                if entry_quote is None:
                    reason = "candidate_entry_quote_missing"
                elif exit_quote is None:
                    reason = f"candidate_{exit_kind}_quote_missing"
                elif str(entry_quote.get("contract_symbol")) != str(trade.get("contract_symbol")):
                    reason = "candidate_entry_contract_mismatch"
                elif str(exit_quote.get("contract_symbol")) != str(trade.get("contract_symbol")):
                    reason = "candidate_exit_contract_mismatch"

        if reason is not None:
            reason_counts[reason] += 1
            excluded.append({
                "trade_id": trade_id,
                "strategy_id": trade.get("strategy_id"),
                "ticker": trade.get("ticker"),
                "contract_symbol": trade.get("contract_symbol"),
                "candidate_id": candidate_id or None,
                "reason": reason,
            })
            continue

        quantity = int(trade.get("contracts") or 0)
        ask = float(entry_quote.get("ask") or 0)  # type: ignore[union-attr]
        bid = float(exit_quote.get("bid") or 0)  # type: ignore[union-attr]
        entry_fill = float(trade.get("entry_price") or 0)
        exit_fill = float(trade.get("exit_price") or 0)
        realized = float(trade.get("realized_pnl") or 0)
        if quantity <= 0 or ask <= 0 or bid < 0 or entry_fill <= 0 or exit_fill < 0:
            reason_counts["invalid_price_or_quantity"] += 1
            excluded.append({
                "trade_id": trade_id, "strategy_id": trade.get("strategy_id"),
                "ticker": trade.get("ticker"), "contract_symbol": trade.get("contract_symbol"),
                "candidate_id": candidate_id, "reason": "invalid_price_or_quantity",
            })
            continue

        multiplier = quantity * 100
        recomputed_actual = (exit_fill - entry_fill) * multiplier
        reference_pnl = (bid - ask) * multiplier
        entry_adverse = (entry_fill - ask) * multiplier
        exit_adverse = (bid - exit_fill) * multiplier
        matched.append({
            "trade_id": trade_id,
            "candidate_id": candidate_id,
            "strategy_id": trade["strategy_id"],
            "ticker": trade["ticker"],
            "contract_symbol": trade["contract_symbol"],
            "contracts": quantity,
            "entry_time": trade["entry_time"],
            "exit_time": trade["exit_time"],
            "registered_exit_minutes": rule.exit_minutes,  # type: ignore[union-attr]
            "tradier_entry_ask": round(ask, 4),
            "alpaca_entry_fill": round(entry_fill, 4),
            "tradier_exit_bid": round(bid, 4),
            "alpaca_exit_fill": round(exit_fill, 4),
            "tradier_reference_pnl": round(reference_pnl, 2),
            "alpaca_realized_pnl": round(realized, 2),
            "entry_cross_feed_adverse_dollars": round(entry_adverse, 2),
            "exit_cross_feed_adverse_dollars": round(exit_adverse, 2),
            "total_cross_feed_adverse_dollars": round(entry_adverse + exit_adverse, 2),
            "actual_pnl_reconciliation_difference": round(realized - recomputed_actual, 4),
            "cross_feed_gap_reconciliation_difference": round(
                reference_pnl - realized - entry_adverse - exit_adverse, 4
            ),
            "entry_quote_source": entry_quote.get("source"),  # type: ignore[union-attr]
            "exit_quote_source": exit_quote.get("source"),  # type: ignore[union-attr]
        })
    conn.close()

    by_strategy = {
        strategy_id: _summary([row for row in matched if row["strategy_id"] == strategy_id])
        for strategy_id in sorted({str(row["strategy_id"]) for row in trades})
    }
    validation = {
        "database_integrity": {"passed": integrity == "ok", "detail": integrity},
        "actual_pnl_reconciles": {
            "passed": all(abs(row["actual_pnl_reconciliation_difference"]) <= .01 for row in matched),
            "largest_absolute_difference": round(max(
                (abs(row["actual_pnl_reconciliation_difference"]) for row in matched), default=0
            ), 4),
        },
        "cross_feed_gap_reconciles": {
            "passed": all(abs(row["cross_feed_gap_reconciliation_difference"]) <= .01 for row in matched),
            "largest_absolute_difference": round(max(
                (abs(row["cross_feed_gap_reconciliation_difference"]) for row in matched), default=0
            ), 4),
        },
    }
    return {
        "purpose": "Exact-contract Tradier candidate quote versus linked Alpaca paper-fill parity audit.",
        "database": str(db_path),
        "trade_id_range": [first_trade_id, last_trade_id],
        "closed_trades": len(trades),
        "matched_trades": len(matched),
        "excluded_trades": len(excluded),
        "excluded_reason_counts": dict(reason_counts),
        "method": (
            "Same candidate, strategy, ticker, contract, quantity, and registered 30/90-minute horizon. "
            "No hypothetical fill is substituted for the broker fill."
        ),
        "overall": _summary(matched),
        "by_strategy": by_strategy,
        "matched_trade_details": matched,
        "excluded_trade_details": excluded,
        "validation": validation,
        "interpretation": {
            "positive_cross_feed_adverse_dollars": "Alpaca paper result was worse than the recorded Tradier quote reference.",
            "not_pure_slippage": "The gap includes quote timing, cross-feed differences, paper-fill modeling, and execution.",
            "portfolio_limit": "This is the matched historical cohort, not an out-of-sample strategy promotion test.",
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--first-trade-id", type=int, required=True)
    parser.add_argument("--last-trade-id", type=int, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = build_report(
        args.database, first_trade_id=args.first_trade_id, last_trade_id=args.last_trade_id,
    )
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")


if __name__ == "__main__":
    main()
