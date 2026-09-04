"""Descriptive paper-fill audit, never a substitute for fresh executable quotes."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from math import isfinite
from zoneinfo import ZoneInfo


def number(value):
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if isfinite(result) else None


def timestamp(value):
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return result if result.tzinfo else result.replace(tzinfo=ZoneInfo("America/New_York"))


def optional_sum(rows, field):
    values = [r[field] for r in rows if r.get(field) is not None]
    return round(sum(values), 6) if values else None


def summarize(rows):
    closed = [r for r in rows if r["status"] == "closed"]
    pnl = [r["recorded_pnl"] for r in closed if r["recorded_pnl"] is not None]
    gains, losses = sum(p for p in pnl if p > 0), -sum(p for p in pnl if p < 0)
    return {
        "trade_rows": len(rows), "closed_rows": len(closed),
        "open_rows": sum(r["status"] == "open" for r in rows),
        "closed_rows_missing_pnl": len(closed)-len(pnl),
        "recorded_pnl": round(sum(pnl), 6) if pnl else None,
        "recorded_profit_factor": round(gains/losses, 6) if losses and len(pnl) == len(closed) else None,
        "gross_profit": round(gains, 6) if pnl else None,
        "gross_loss": round(losses, 6) if pnl else None,
        "paired_entry_quotes": sum(r["entry_difference_dollars"] is not None for r in rows),
        "paired_exit_quotes": sum(r["exit_difference_dollars"] is not None for r in rows),
        "paired_round_trips": sum(r["saved_quote_round_trip"] is not None for r in rows),
        "entry_difference_dollars": optional_sum(rows, "entry_difference_dollars"),
        "exit_difference_dollars": optional_sum(rows, "exit_difference_dollars"),
        "saved_quote_round_trip": optional_sum(rows, "saved_quote_round_trip"),
        "pnl_arithmetic_issues": [r["trade_id"] for r in rows if r["pnl_arithmetic_issue"]],
    }


def analyze(trades, quotes):
    """Compare matching contract rows without filling missing data from nearby marks."""
    if len({t["id"] for t in trades}) != len(trades):
        raise ValueError("Duplicate trade rows would inflate performance")
    by_trade = defaultdict(list)
    for quote in quotes:
        by_trade[quote["trade_id"]].append(quote)
    rows, groups = [], defaultdict(list)
    for trade in trades:
        exact = [q for q in by_trade[trade["id"]]
                 if q["contract_symbol"] == trade["contract_symbol"] and timestamp(q["observed_at"])]
        exact.sort(key=lambda q: (timestamp(q["observed_at"]), q["id"]))
        # First frozen observation per leg, not a more favorable later quote.
        entry = next((q for q in exact if q["observation_kind"] == "entry"), {})
        exit_quote = next((q for q in exact if q["observation_kind"] == "exit"), {})
        qty = number(trade.get("contracts"))
        multiplier = qty * 100 if qty is not None and qty > 0 and qty.is_integer() else None
        entry_fill, exit_fill = number(trade.get("entry_price")), number(trade.get("exit_price"))
        entry_ask, exit_bid = number(entry.get("ask")), number(exit_quote.get("bid"))
        entry_diff = ((entry_fill-entry_ask)*multiplier
                      if multiplier and entry_fill is not None and entry_fill >= 0
                      and entry_ask is not None and entry_ask > 0 else None)
        exit_diff = ((exit_bid-exit_fill)*multiplier
                     if multiplier and trade["status"] == "closed" and exit_fill is not None
                     and exit_fill >= 0 and exit_bid is not None and exit_bid >= 0 else None)
        quote_pnl = ((exit_bid-entry_ask)*multiplier
                     if entry_diff is not None and exit_diff is not None else None)
        pnl = number(trade.get("realized_pnl")) if trade["status"] == "closed" else None
        price_pnl = ((exit_fill-entry_fill)*multiplier
                     if multiplier and entry_fill is not None and exit_fill is not None else None)
        row = {"trade_id": trade["id"], "ticker": trade["ticker"],
               "strategy_id": trade["strategy_id"], "status": trade["status"],
               "entry_time": trade["entry_time"], "recorded_pnl": pnl,
               "entry_quote_source": entry.get("source"), "exit_quote_source": exit_quote.get("source"),
               "entry_difference_dollars": entry_diff, "exit_difference_dollars": exit_diff,
               "saved_quote_round_trip": quote_pnl,
               "pnl_arithmetic_issue": bool(pnl is not None and price_pnl is not None and abs(pnl-price_pnl) > .011),
               "quote_market_freshness": "not_verified"}
        rows.append(row)
        groups[(row["strategy_id"], row["ticker"])].append(row)
    return {
        "evidence_class": "recorded_paper_fills_with_descriptive_quote_comparison",
        "cost_basis": "Recorded paper P&L; no additional live fees or slippage assumed.",
        "quote_comparison_warning": "Saved prices may be stale or from different times. Differences are not proven slippage. Missing data stays null; nearby marks never substitute for exit quotes.",
        "live_ready": False,
        "summary": summarize(rows),
        "by_strategy_ticker": [dict(strategy_id=s, ticker=t, **summarize(v)) for (s,t),v in sorted(groups.items())],
        "trades": rows,
    }
