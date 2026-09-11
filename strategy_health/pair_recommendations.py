"""Account-local recommendations. Never changes order authority by itself.

All signals remain in research. Non-overlapping completed positions form the
decision sample, so a burst of overlapping plays cannot inflate confidence.
These are review triggers, not a guarantee of future profits.
"""
from datetime import datetime, timezone
from hashlib import sha256
import json
import math
from statistics import median
from zoneinfo import ZoneInfo

POLICY = {
    "version": "completed-trades-v1",
    "minimum_completed_trades": 20,
    "validation_trades": 6,
    "promising_trades": 5,
    "review_recent_trades": 10,
    "target_profit_factor": 1.5,
    "review_profit_factor_below": 1.0,
    "maximum_winner_share_pct": 35,
    "minimum_market_days": 0,
    "minimum_result_days": 0,
}


def timestamp(value):
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo("America/New_York"))
    return parsed.astimezone(timezone.utc)


def consent_scope(settings, sid, ticker):
    mode = "paper" if settings.get("paper_trading", True) else "live"
    return f"{mode}:{settings.get('active_broker_account_id') or ''}:{sid}:{ticker}"


def summarize(rows):
    profits = [row["pnl"] for row in rows]
    gains = sum(p for p in profits if p > 0)
    losses = -sum(p for p in profits if p < 0)
    return {
        "option_results": len(rows),
        "profit_factor": round(gains / losses, 2) if losses else "infinite" if gains else None,
        "net_one_contract_pnl": round(sum(profits), 2),
        "median_one_contract_pnl": round(median(profits), 2) if profits else None,
        "wins": sum(p > 0 for p in profits),
        "win_rate_pct": round(sum(p > 0 for p in profits) / len(profits) * 100, 1) if profits else None,
        "largest_winner_share_pct": round(max(profits, default=0) / gains * 100, 2) if gains else None,
    }


def numeric(value):
    return math.inf if value == "infinite" else float(value or 0)


def assess(rows):
    valid = []
    for row in rows:
        try:
            start, end = timestamp(row["entry_at"]), timestamp(row["exit_at"])
            pnl = float(row["pnl"])
            if end <= start or not math.isfinite(pnl):
                continue
            valid.append({**row, "pnl": pnl, "start": start, "end": end})
        except (KeyError, TypeError, ValueError):
            continue
    valid.sort(key=lambda row: (row["start"], str(row.get("id", ""))))
    independent, end = [], None
    for row in valid:
        if end is None or row["start"] >= end:
            independent.append(row)
            end = row["end"]
    # The latest twenty positions are split in time, never chosen by profit.
    window = independent[-POLICY["minimum_completed_trades"]:]
    training, validation = window[:-6], window[-6:]
    recent = independent[-POLICY["review_recent_trades"]:]
    total, train, check, last = map(summarize, (window, training, validation, recent))
    reasons = []
    if len(window) < 20:
        reasons.append(f"Needs {20 - len(window)} more non-overlapping completed tests")
    if numeric(train["profit_factor"]) < 1.5:
        reasons.append("First 14 tests need PF 1.5 or higher")
    if numeric(check["profit_factor"]) < 1.5:
        reasons.append("Latest 6 tests need PF 1.5 or higher")
    if (total["median_one_contract_pnl"] or 0) <= 0:
        reasons.append("The typical test must finish with a profit after costs")
    if total["largest_winner_share_pct"] is not None and total["largest_winner_share_pct"] > 35:
        reasons.append("One winning test supplies more than 35% of total gains")
    qualified = not reasons
    review = len(recent) == 10 and numeric(last["profit_factor"]) < 1 and last["net_one_contract_pnl"] < 0
    promising = len(independent) >= 5 and numeric(total["profit_factor"]) >= 1.5 and (total["median_one_contract_pnl"] or 0) > 0
    fingerprint = sha256(json.dumps([(r.get("id"), r["pnl"], str(r["end"])) for r in window]).encode()).hexdigest()[:20]
    return {
        "policy_version": POLICY["version"], "qualified": qualified,
        "review_active": review, "promising": promising,
        "completed_trades": len(valid), "independent_trades": len(independent),
        "overlapping_trades": len(valid) - len(independent),
        "remaining_trades": max(0, 20-len(independent)),
        "training": train, "validation": check, "recent": last,
        "reasons": reasons, "fingerprint": fingerprint,
        "first_test_at": str(valid[0]["entry_at"]) if valid else None,
        "last_test_at": str(valid[-1]["exit_at"]) if valid else None,
    }


def recommendations(matrix, settings):
    """Use the exact account/version/contract/exit evidence displayed in Research."""
    from config.strategy_catalog import REVIEWED_STRATEGIES, reviewed_strategy_integrity_errors
    from config.strategy_live_promotion import review_live_promotion
    paper = bool(settings.get("paper_trading", True))
    decisions = settings.get("strategy_pair_review_decisions", {}) or {}
    result = []
    errors = reviewed_strategy_integrity_errors()
    for strategy in matrix["strategies"]:
        sid = strategy["strategy_id"]
        rule = REVIEWED_STRATEGIES.get(sid)
        for pair in strategy["pairs"]:
            evidence = pair.get("recommendation") or {}
            kind = "review_active" if pair["tradable"] and evidence.get("review_active") else "new_match" if not pair["tradable"] and evidence.get("qualified") else None
            if kind is None:
                continue
            key = f"{consent_scope(settings, sid, pair['ticker'])}:{kind}"
            if decisions.get(key) == evidence.get("fingerprint"):
                continue
            executable = bool(rule and not rule.observation_only and sid not in errors)
            live = bool(executable and review_live_promotion(rule, pair["ticker"]).ready)
            switch_on = bool(rule and settings.get(rule.setting_key, False))
            can_enable = executable and switch_on and (paper or live)
            metrics = evidence["recent"] if kind == "review_active" else {**evidence["validation"], "option_results": evidence["independent_trades"]}
            result.append({
                "strategy_id": sid, "ticker": pair["ticker"], "strategy_version": strategy["version"],
                "display_name": strategy["display_name"], "kind": kind,
                "fingerprint": evidence["fingerprint"], "evidence": evidence,
                "profit_factor": metrics["profit_factor"], "completed_trades": metrics["option_results"],
                "net_pnl": metrics["net_one_contract_pnl"],
                "account_mode": "paper" if paper else "live", "can_enable": can_enable,
                "blocker": None if can_enable else "Research passed; the matching order-entry and exit route still needs implementation and review." if not executable else "The strategy's trading switch is off. This recommendation will not switch on other tickers." if not switch_on else "Research passed; live execution review is still required.",
            })
    return {"recommendations": result, "policy": POLICY, "evaluated_strategies": len(matrix["strategies"])}


def decide(matrix, settings, sid, ticker, decision, fingerprint):
    """Revalidate a visible decision server-side; never trust posted PF or version."""
    sid, ticker = sid.strip().upper(), ticker.strip().upper()
    item = next((r for r in recommendations(matrix, settings)["recommendations"]
                 if r["strategy_id"] == sid and r["ticker"] == ticker), None)
    if not item or item["fingerprint"] != fingerprint:
        raise ValueError("Results changed. Refresh the recommendation before deciding.")
    allowed = {"research_only", "keep_trading"} if item["kind"] == "review_active" else {"enable", "keep_off"}
    if decision not in allowed:
        raise ValueError("This action does not match the recommendation.")
    if decision == "enable" and not item["can_enable"]:
        raise ValueError(item["blocker"])
    mode_key = consent_scope(settings, sid, ticker)
    updates = {}
    if decision in {"research_only", "enable"}:
        pauses = dict(settings.get("strategy_pair_pauses") or {})
        pauses[mode_key] = decision == "research_only"
        updates["strategy_pair_pauses"] = pauses
    if decision == "enable":
        approvals = dict(settings.get("strategy_pair_approvals") or {})
        approvals[mode_key] = {"strategy_version": item["strategy_version"], "user_approved": True,
                               "strategy_id": sid, "ticker": ticker,
                               "evidence_fingerprint": fingerprint, "approved_at": datetime.now(timezone.utc).isoformat()}
        updates["strategy_pair_approvals"] = approvals
    decisions = dict(settings.get("strategy_pair_review_decisions") or {})
    decisions[f"{mode_key}:{item['kind']}"] = fingerprint
    updates["strategy_pair_review_decisions"] = decisions
    return updates
