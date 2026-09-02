"""Summarize durable option-order execution evidence by broker.

This is an observability report, not a trading simulator.  It measures what
the broker actually acknowledged and filled so entry misses and exit leakage
cannot be confused with strategy performance.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any


FILL_EVENTS = {"filled", "partial_filled"}


def _adverse_slippage(side: str, limit_price: float | None, fill_price: float | None) -> float | None:
    if limit_price is None or fill_price is None:
        return None
    return fill_price - limit_price if side == "buy" else limit_price - fill_price


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    def empty_bucket() -> dict[str, Any]:
        return {
            "attempts": 0, "filled_attempts": 0, "unfilled_attempts": 0,
            "market_fallback_attempts": 0, "attempts_with_issues": 0,
            "requested_contracts": 0, "filled_contracts": 0,
            "adverse_slippage_dollars": 0.0, "priced_fill_attempts": 0,
        }

    attempts: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        attempts[str(row["attempt_id"])].append(row)

    buckets: dict[str, dict[str, Any]] = {}
    broker_buckets: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    issue_types: Counter[str] = Counter()
    details: list[dict[str, Any]] = []
    for attempt_id, events in attempts.items():
        events.sort(key=lambda item: (item.get("event_time") or "", item.get("id") or 0))
        first = events[0]
        side = str(first.get("side") or "unknown").lower()
        intent = str(first.get("position_intent") or "unknown")
        broker = str(first.get("broker") or "unknown").lower()
        key = intent if intent != "unknown" else side
        bucket = buckets.setdefault(key, empty_bucket())
        broker_bucket = broker_buckets[broker].setdefault(key, empty_bucket())
        target_buckets = (bucket, broker_bucket)
        for target in target_buckets:
            target["attempts"] += 1

        submit = next((event for event in events if event.get("event_type") == "submit_attempt"), first)
        authoritative_quotes = [
            event for event in events if event.get("event_type") == "authoritative_quote"
        ]
        requotes = [event for event in events if event.get("event_type") == "broker_requote"]
        reference = (
            authoritative_quotes[-1]
            if authoritative_quotes else (requotes[-1] if requotes else submit)
        )
        execution_summaries = [
            event for event in events if event.get("event_type") == "execution_summary"
        ]
        fills = [event for event in events if event.get("event_type") in FILL_EVENTS and event.get("fill_price") is not None]
        fill = fills[-1] if fills else None
        requested_qty = int(submit.get("requested_qty") or first.get("requested_qty") or 0)
        filled_qty = int((fill or {}).get("filled_qty") or 0)
        used_market = any(event.get("event_type") == "fallback_acknowledged" for event in events)
        issues = sorted({str(event.get("event_type")) for event in events if event.get("is_issue")})
        for issue in issues:
            issue_types[issue] += 1

        for target in target_buckets:
            target["requested_contracts"] += requested_qty
            target["filled_contracts"] += filled_qty
            target["market_fallback_attempts"] += int(used_market)
            target["attempts_with_issues"] += int(bool(issues))
            if fill:
                target["filled_attempts"] += 1
            else:
                target["unfilled_attempts"] += 1

        limit_price = reference.get("limit_price")
        fill_price = (fill or {}).get("fill_price")
        slip = _adverse_slippage(side, limit_price, fill_price)
        slip_dollars = None
        if slip is not None:
            slip_dollars = round(slip * filled_qty * 100, 2)
            for target in target_buckets:
                target["adverse_slippage_dollars"] += slip_dollars
                target["priced_fill_attempts"] += 1

        details.append({
            "attempt_id": attempt_id,
            "broker": broker,
            "started_at": first.get("event_time"),
            "ticker": first.get("ticker"),
            "strategy_id": first.get("strategy_id"),
            "side": side,
            "position_intent": intent,
            "requested_qty": requested_qty,
            "filled_qty": filled_qty,
            "reference_limit": limit_price,
            "reference_source": (
                "tradier" if authoritative_quotes else
                ("alpaca" if requotes else "submitted_limit")
            ),
            "quote_latency_ms": reference.get("latency_ms"),
            "submit_ack_latency_ms": next(
                (event.get("latency_ms") for event in events
                 if event.get("event_type") == "acknowledged"),
                None,
            ),
            "submit_to_fill_latency_ms": (
                execution_summaries[-1].get("latency_ms")
                if execution_summaries else None
            ),
            "fill_price": fill_price,
            "adverse_slippage_dollars": slip_dollars,
            "used_market_fallback": used_market,
            "issues": issues,
            "final_event": events[-1].get("event_type"),
            "final_status": events[-1].get("status"),
        })

    all_buckets = list(buckets.values()) + [
        bucket for intents in broker_buckets.values() for bucket in intents.values()
    ]
    for bucket in all_buckets:
        total = bucket["attempts"]
        bucket["fill_rate_pct"] = round(100 * bucket["filled_attempts"] / total, 1) if total else 0.0
        bucket["adverse_slippage_dollars"] = round(bucket["adverse_slippage_dollars"], 2)

    ordered_rows = sorted(rows, key=lambda row: row.get("event_time") or "")
    return {
        "generated_at": datetime.now().astimezone().isoformat(),
        "evidence_window": {
            "first_event": ordered_rows[0].get("event_time") if ordered_rows else None,
            "last_event": ordered_rows[-1].get("event_time") if ordered_rows else None,
            "event_count": len(rows),
            "attempt_count": len(attempts),
        },
        "by_intent": buckets,
        "by_broker_and_intent": dict(broker_buckets),
        "issue_attempts_by_type": dict(issue_types.most_common()),
        "attempts": details,
        "interpretation": {
            "fill_rate": "Broker-confirmed fills divided by submitted attempts; an unfilled bounded limit is not a trade.",
            "adverse_slippage": "Buy fill above the working limit or sell fill below it, multiplied by contracts and 100.",
            "warning": "Do not blend execution leakage into strategy edge; report both separately.",
            "reference_source": "The authoritative natural-side quote is kept separate from the working limit and confirmed broker fill; broker-specific buckets prevent Alpaca and Tradier evidence from being blended.",
        },
    }


def load_events(database: Path) -> list[dict[str, Any]]:
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    try:
        return [dict(row) for row in connection.execute(
            "SELECT * FROM broker_order_events ORDER BY event_time, id"
        )]
    finally:
        connection.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = summarize(load_events(args.database))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"output": str(args.output), **report["evidence_window"], "by_intent": report["by_intent"]}, indent=2))


if __name__ == "__main__":
    main()
