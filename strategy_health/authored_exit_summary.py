"""Keep causal exit evidence separate from fixed-horizon comparisons."""
from collections import Counter
import math
from statistics import median

from config.market_constants import COMMISSION_PER_CONTRACT
from strategy_health.impulse_exit import PROTOCOL, et


def load_authored_exits(conn, account, cutoff):
    # Older read-only archive fixtures may predate this additive migration.
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='research_strategy_exits'").fetchone():
        return {}
    return {row["candidate_id"]: dict(row) for row in conn.execute("""
        SELECT e.* FROM research_strategy_exits e JOIN shadow_candidates s
        ON s.candidate_id=e.candidate_id WHERE e.protocol=? AND s.observed_at>=?
        AND COALESCE(s.broker_account_id,'')=? ORDER BY s.observed_at,s.candidate_id
        """, (PROTOCOL, cutoff, account or ''))}


def authored_summary(samples, exits):
    selected = [exits[s["candidate_id"]] for s in samples if s["candidate_id"] in exits]
    profits, days, closed_batches = [], set(), Counter()
    for row in selected:
        if row["status"] != "priced":
            continue
        ask, bid = row["entry_ask"], row["bid"]
        if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in (ask, bid)) or ask <= 0 or bid < 0:
            continue
        # Same conservative costs as timer comparisons; losses include zero bids.
        profits.append(round((max(0, bid - .01) - (ask + .01))*100 - 2*COMMISSION_PER_CONTRACT, 2))
        closed_batches[row["decision_at"]] += profits[-1]
        days.add(et(row["decision_at"]).date().isoformat())
    gains, losses = sum(p for p in profits if p > 0), -sum(p for p in profits if p < 0)
    peak = running = drawdown = 0
    for _, profit in sorted(closed_batches.items()):
        running += profit
        peak = max(peak, running)
        drawdown = max(drawdown, peak-running)
    counts = Counter(r["status"] for r in selected)
    return {
        "protocol": PROTOCOL, "tracked": len(selected), "option_results": len(profits),
        "option_result_days": len(days),
        "profit_factor": round(gains/losses, 2) if losses else ("infinite" if gains else None),
        "net_one_contract_pnl": round(sum(profits), 2) if profits else None,
        "average_one_contract_pnl": round(sum(profits)/len(profits), 2) if profits else None,
        "median_one_contract_pnl": round(median(profits), 2) if profits else None,
        "maximum_drawdown_one_contract": round(drawdown, 2) if profits else None,
        "collecting": counts["collecting"], "pending_quote": counts["pending_quote"],
        "missing_quote": counts["missing_quote"], "unmeasurable": counts["unmeasurable"],
        "reasons": dict(Counter(r["reason"] for r in selected if r["reason"])),
        "recent": [{key: r[key] for key in (
            "candidate_id", "contract_symbol", "status", "reason", "decision_at", "entry_ask", "bid", "bid_at",
        )} for r in selected[-5:]],
    }
