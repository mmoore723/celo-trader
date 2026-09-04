"""Compare paper fills with saved Tradier bid/ask paths without rewriting history.

The broker's paper P&L remains the accounting record.  This module produces a
separate, deliberately conservative research view: enter at the saved Tradier
ask and exit at a saved Tradier bid.  It never invents a quote or treats a
missing price as zero.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from math import isfinite
from zoneinfo import ZoneInfo


EXACT_EXIT_SOURCES = frozenset({"tradier_pre_submit_exit_quote"})
LEGACY_MARK_SOURCES = frozenset({"tradier_quote"})
ENTRY_SOURCES = frozenset({"tradier_chain"})
MAX_EXACT_QUOTE_AGE_SECONDS = 120


def _number(value):
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if isfinite(result) else None


def _timestamp(value):
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return result if result.tzinfo else result.replace(tzinfo=ZoneInfo("America/New_York"))


def _valid_market(quote):
    bid, ask = _number(quote.get("bid")), _number(quote.get("ask"))
    return bid is not None and ask is not None and bid >= 0 and ask > 0 and bid <= ask


def _summarize(rows):
    quote_pnl = [row["quote_pnl_after_fees"] for row in rows]
    gross_profit = sum(value for value in quote_pnl if value > 0)
    gross_loss = -sum(value for value in quote_pnl if value < 0)
    recorded = sum(row["recorded_pnl"] for row in rows)
    quote_before_fees = sum(row["quote_pnl_before_fees"] for row in rows)
    return {
        "measured_trades": len(rows),
        "exact_exit_quotes": sum(row["exit_evidence"] == "exact_pre_submit" for row in rows),
        "legacy_nearby_marks": sum(row["exit_evidence"] == "legacy_nearby_mark" for row in rows),
        "recorded_paper_pnl": round(recorded, 6) if rows else None,
        "quote_pnl_before_fees": round(quote_before_fees, 6) if rows else None,
        "quote_pnl_after_fees": round(sum(quote_pnl), 6) if rows else None,
        "quote_profit_factor_after_fees": (
            round(gross_profit / gross_loss, 6) if gross_loss else None
        ),
        "paper_minus_quote_before_fees": (
            round(recorded - quote_before_fees, 6) if rows else None
        ),
        "gross_profit_after_fees": round(gross_profit, 6) if rows else None,
        "gross_loss_after_fees": round(gross_loss, 6) if rows else None,
    }


def analyze(trades, quotes, *, max_legacy_age_seconds=120, fee_per_contract_side=0.12):
    """Return quote-aligned P&L for closed paper trades with usable evidence.

    Exact pre-submit exit rows are preferred.  Older rows may use the nearest
    preceding exact-contract Tradier mark only when it is within the declared
    age bound.  Those legacy rows remain labeled estimates and are never
    presented as an executable quote captured at the exit decision.
    """
    if max_legacy_age_seconds <= 0:
        raise ValueError("Legacy quote age must be positive")
    fee = _number(fee_per_contract_side)
    if fee is None or fee < 0:
        raise ValueError("Per-contract fee must be finite and non-negative")
    if len({trade.get("id") for trade in trades}) != len(trades):
        raise ValueError("Duplicate trade rows would inflate performance")

    by_trade = defaultdict(list)
    for quote in quotes:
        by_trade[quote.get("trade_id")].append(quote)

    rows = []
    excluded = defaultdict(int)
    for trade in trades:
        if trade.get("status") != "closed":
            excluded["not_closed"] += 1
            continue
        entry_time, exit_time = _timestamp(trade.get("entry_time")), _timestamp(trade.get("exit_time"))
        contracts = _number(trade.get("contracts"))
        recorded_pnl = _number(trade.get("realized_pnl"))
        if not entry_time or not exit_time or exit_time < entry_time:
            excluded["invalid_trade_time"] += 1
            continue
        if contracts is None or contracts <= 0 or not contracts.is_integer() or recorded_pnl is None:
            excluded["invalid_trade_value"] += 1
            continue

        exact = [quote for quote in by_trade[trade.get("id")]
                 if quote.get("contract_symbol") == trade.get("contract_symbol")
                 and _timestamp(quote.get("observed_at")) and _valid_market(quote)]
        exact.sort(key=lambda quote: (_timestamp(quote["observed_at"]), quote.get("id", 0)))
        entry_candidates = [quote for quote in exact
                            if quote.get("observation_kind") == "entry"
                            and quote.get("source") in ENTRY_SOURCES
                            and abs((_timestamp(quote["observed_at"]) - entry_time).total_seconds())
                            <= MAX_EXACT_QUOTE_AGE_SECONDS]
        if not entry_candidates:
            excluded["missing_entry_ask"] += 1
            continue
        entry = min(entry_candidates, key=lambda quote: abs(
            (_timestamp(quote["observed_at"]) - entry_time).total_seconds()))

        exact_exits = [quote for quote in exact
                       if quote.get("observation_kind") == "exit"
                       and quote.get("source") in EXACT_EXIT_SOURCES
                       and abs((_timestamp(quote["observed_at"]) - exit_time).total_seconds())
                       <= MAX_EXACT_QUOTE_AGE_SECONDS]
        if exact_exits:
            exit_quote = min(exact_exits, key=lambda quote: abs(
                (_timestamp(quote["observed_at"]) - exit_time).total_seconds()))
            exit_evidence = "exact_pre_submit"
            exit_age = abs((_timestamp(exit_quote["observed_at"]) - exit_time).total_seconds())
        else:
            candidates = []
            for quote in exact:
                observed = _timestamp(quote["observed_at"])
                age = (exit_time - observed).total_seconds()
                if (quote.get("observation_kind") == "mark"
                        and quote.get("source") in LEGACY_MARK_SOURCES
                        and 0 <= age <= max_legacy_age_seconds):
                    candidates.append((age, quote))
            if not candidates:
                excluded["missing_exit_bid"] += 1
                continue
            exit_age, exit_quote = min(candidates, key=lambda item: item[0])
            exit_evidence = "legacy_nearby_mark"

        multiplier = int(contracts) * 100
        entry_ask, exit_bid = float(entry["ask"]), float(exit_quote["bid"])
        quote_before_fees = (exit_bid - entry_ask) * multiplier
        fees = int(contracts) * fee * 2
        rows.append({
            "trade_id": trade["id"],
            "ticker": trade.get("ticker"),
            "strategy_id": trade.get("strategy_id"),
            "entry_time": trade.get("entry_time"),
            "exit_time": trade.get("exit_time"),
            "contracts": int(contracts),
            "entry_ask": entry_ask,
            "exit_bid": exit_bid,
            "exit_evidence": exit_evidence,
            "exit_quote_age_seconds": round(exit_age, 3),
            "recorded_pnl": round(recorded_pnl, 6),
            "quote_pnl_before_fees": round(quote_before_fees, 6),
            "modeled_passthrough_fees": round(fees, 6),
            "quote_pnl_after_fees": round(quote_before_fees - fees, 6),
            "paper_minus_quote_before_fees": round(recorded_pnl - quote_before_fees, 6),
        })

    groups = defaultdict(list)
    for row in rows:
        groups[(row["strategy_id"], row["ticker"])].append(row)
    exact_rows = [row for row in rows if row["exit_evidence"] == "exact_pre_submit"]
    legacy_rows = [row for row in rows if row["exit_evidence"] == "legacy_nearby_mark"]
    return {
        "evidence_class": "saved_tradier_ask_to_bid_quote_replay",
        "warning": (
            "Exact rows use saved pre-submit exit quotes. Legacy rows use the nearest prior "
            "saved Tradier mark inside the age limit and are estimates, not proven executable fills. "
            "Observed-at is application receive time; it does not prove the exchange timestamp."
        ),
        "cost_model": {
            "entry": "saved Tradier ask",
            "exit": "saved Tradier bid",
            "fee_per_contract_per_side": fee,
            "extra_slippage": 0.0,
            "monthly_subscription": "not allocated to trades",
        },
        "summary": _summarize(rows),
        "exact_exit_summary": _summarize(exact_rows),
        "legacy_exit_summary": _summarize(legacy_rows),
        "by_strategy_ticker": [
            dict(strategy_id=strategy, ticker=ticker, **_summarize(group_rows))
            for (strategy, ticker), group_rows in sorted(groups.items())
        ],
        "excluded": dict(sorted(excluded.items())),
        "trades": rows,
        "live_ready": False,
    }
