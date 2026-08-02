"""Read-only strategy scorecard built from paper/live decision and outcome data."""
from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
import json

from database import get_conn, _now_et


MIN_ACTIONABLE_TRADES = 20
MAIN_TIER = "main"
OPPORTUNITY_TIER = "opportunity"


def _new_row(strategy_id: str) -> dict:
    """Create one read-only aggregate row for a strategy/tier pair."""
    return {
        "strategy_id": strategy_id, "closed_trades": 0, "wins": 0,
        "pnl": 0.0, "blocked_signals": 0, "entered_signals": 0,
        "block_reasons": defaultdict(int),
    }


def _normalise_tier(value: object) -> str:
    """Keep legacy, missing, and future tag spellings safely comparable."""
    if isinstance(value, bool):
        return OPPORTUNITY_TIER if value else MAIN_TIER
    value = str(value or "").strip().lower()
    return OPPORTUNITY_TIER if value in {"opportunity", "opportunity_tier", "tier_2", "secondary"} else MAIN_TIER


def _tier_from_context(raw_context: object) -> str:
    """Read a tier tag written into signal context without trusting malformed JSON."""
    if not raw_context:
        return MAIN_TIER
    try:
        context = json.loads(raw_context) if isinstance(raw_context, str) else raw_context
    except (TypeError, ValueError):
        return MAIN_TIER
    if not isinstance(context, dict):
        return MAIN_TIER
    return _normalise_tier(context.get("trade_tier", context.get("opportunity_tier")))


def _finalise(rows: dict[tuple[str, str], dict]) -> list[dict]:
    """Calculate display metrics after all trade and signal evidence is collected."""
    result = []
    for row in rows.values():
        n = row["closed_trades"]
        row["pnl"] = round(row["pnl"], 2)
        row["win_rate"] = round(row["wins"] / n * 100, 1) if n else None
        row["expectancy"] = round(row["pnl"] / n, 2) if n else None
        row["sample_status"] = "actionable" if n >= MIN_ACTIONABLE_TRADES else "collecting_data"
        row["block_reasons"] = dict(sorted(row["block_reasons"].items(), key=lambda item: -item[1]))
        result.append(dict(row))
    return sorted(result, key=lambda row: (row["sample_status"] != "actionable", -row["pnl"]))


def build_scorecard(days: int = 30) -> dict:
    """Combine closed outcomes and signal decisions, split by reporting tier only."""
    days = max(1, min(int(days), 365))
    cutoff = (_now_et() - timedelta(days=days)).isoformat()
    rows: dict[tuple[str, str], dict] = {}
    trade_tiers: dict[int, str] = {}
    with get_conn() as conn:
        trade_columns = {row[1] for row in conn.execute("PRAGMA table_info(trades)")}
        # `tier` is the lifecycle schema name. `trade_tier` remains accepted
        # for any earlier rollout that used the more explicit name.
        tier_column = next((name for name in ("tier", "trade_tier") if name in trade_columns), None)
        tier_select = f", {tier_column}" if tier_column else ""
        journal_columns = {row[1] for row in conn.execute("PRAGMA table_info(signal_journal)")}
        journal_tier = next((name for name in ("tier", "trade_tier") if name in journal_columns), None)
        journal_tier_select = f"{journal_tier} AS tier" if journal_tier else "NULL AS tier"
        journal_trade_id = "trade_id" if "trade_id" in journal_columns else "NULL AS trade_id"
        journal_context = "context_json" if "context_json" in journal_columns else "NULL AS context_json"
        trades = conn.execute(
            f"SELECT id, strategy_id, realized_pnl{tier_select} FROM trades "
            "WHERE status='closed' AND exit_time >= ?", (cutoff,)
        ).fetchall()
        signals = conn.execute(
            f"SELECT strategy_id, outcome, reason_code, {journal_trade_id}, {journal_context}, "
            f"{journal_tier_select} "
            "FROM signal_journal WHERE ts >= ?",
            (cutoff,),
        ).fetchall()
    for signal in signals:
        if signal["outcome"] == "entered" and signal["trade_id"] is not None:
            tier = _normalise_tier(signal["tier"]) if journal_tier else _tier_from_context(signal["context_json"])
            trade_tiers[int(signal["trade_id"])] = tier
    for trade in trades:
        sid = trade["strategy_id"] or "UNKNOWN"
        tier = _normalise_tier(trade["trade_tier"]) if tier_column else trade_tiers.get(trade["id"], MAIN_TIER)
        row = rows.setdefault((sid, tier), _new_row(sid))
        pnl = float(trade["realized_pnl"] or 0.0)
        row["closed_trades"] += 1; row["pnl"] += pnl
        row["wins"] += int(pnl > 0)
    for signal in signals:
        sid = signal["strategy_id"] or "UNKNOWN"
        tier = _normalise_tier(signal["tier"]) if journal_tier else _tier_from_context(signal["context_json"])
        row = rows.setdefault((sid, tier), _new_row(sid))
        if signal["outcome"] == "entered":
            row["entered_signals"] += 1
        else:
            row["blocked_signals"] += 1
            row["block_reasons"][signal["reason_code"] or "unknown"] += 1
    by_tier = {MAIN_TIER: {}, OPPORTUNITY_TIER: {}}
    for (sid, tier), row in rows.items():
        by_tier.setdefault(tier, {})[(sid, tier)] = row
    return {
        "days": days,
        "minimum_actionable_trades": MIN_ACTIONABLE_TRADES,
        # Existing consumers can keep using this as the main-tier scorecard.
        "strategies": _finalise(by_tier[MAIN_TIER]),
        # Opportunity results are deliberately isolated; they never blend into main evidence.
        "opportunity_strategies": _finalise(by_tier[OPPORTUNITY_TIER]),
    }
