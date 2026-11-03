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
    from config.strategy_catalog import REVIEWED_STRATEGIES
    rule = REVIEWED_STRATEGIES.get(sid)
    if rule and rule.authored_exit_order_route:
        return f"shared:{sid}:{ticker}"
    mode = "paper" if settings.get("paper_trading", True) else "live"
    return f"{mode}:{settings.get('active_broker_account_id') or ''}:{sid}:{ticker}"


def summarize(rows):
    profits = [row["pnl"] for row in rows]
    gains = sum(p for p in profits if p > 0)
    losses = -sum(p for p in profits if p < 0)
    starts, ends = [], []
    for row in rows:
        for values, parsed_key, raw_key in ((starts, 'start', 'entry_at'), (ends, 'end', 'exit_at')):
            value = row.get(parsed_key) or row.get(raw_key)
            if value is not None:
                try:
                    values.append(timestamp(value))
                except (TypeError, ValueError):
                    pass
    return {
        "option_results": len(rows),
        "period_start": min(starts).isoformat() if len(starts) == len(rows) and starts else None,
        "period_end": max(ends).isoformat() if len(ends) == len(rows) and ends else None,
        "profit_factor": round(gains / losses, 2) if losses else "infinite" if gains else None,
        "net_one_contract_pnl": round(sum(profits), 2),
        "median_one_contract_pnl": round(median(profits), 2) if profits else None,
        "wins": sum(p > 0 for p in profits),
        "win_rate_pct": round(sum(p > 0 for p in profits) / len(profits) * 100, 1) if profits else None,
        "largest_winner_share_pct": round(max(profits, default=0) / gains * 100, 2) if gains else None,
    }


def numeric(value):
    return math.inf if value == "infinite" else float(value or 0)


def period_label(summary):
    if not summary['period_start'] or not summary['period_end']:
        return 'dates not recorded'
    return ' to '.join(timestamp(summary[key]).astimezone(ZoneInfo('America/New_York')).strftime('%b %d, %Y')
                       for key in ('period_start', 'period_end'))


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
        reasons.append(f"Tests dated {period_label(train)} need PF 1.5 or higher")
    if numeric(check["profit_factor"]) < 1.5:
        reasons.append(f"Tests dated {period_label(check)} need PF 1.5 or higher")
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
    from strategy_health.exit_protocols import PROTOCOLS
    paper = bool(settings.get("paper_trading", True))
    decisions = settings.get("strategy_pair_review_decisions", {}) or {}
    result = []
    errors = reviewed_strategy_integrity_errors()
    from config.research_order_specs import execution_id
    from config.admin_strategy_overrides import allowed_ticker
    for strategy in matrix["strategies"]:
        from config.strategy_retirement import is_retired
        if is_retired(settings, strategy['strategy_id'], strategy['version']):
            continue
        for pair in strategy["pairs"]:
            sid = execution_id(strategy["strategy_id"], strategy['version'], pair['ticker'])
            if is_retired(settings, sid, strategy['version']):
                continue
            rule = REVIEWED_STRATEGIES.get(sid)
            # Evidence snapshots may predate an explicit activation. Resolve
            # current grants from settings without rewriting cached evidence.
            tradable = pair['tradable']
            from config.admin_strategy_overrides import active, key as grant_key
            if grant_key(sid, pair['ticker']) in (settings.get('admin_strategy_overrides') or {}):
                tradable = bool(rule and rule.version == strategy['version']
                                and settings.get(rule.setting_key, False)
                                and active(settings, sid, pair['ticker']))
            evidence = pair.get("recommendation") or {}
            from strategy_health.closed_trade_guard import is_paused
            paused = (settings.get('strategy_pair_pauses') or {}).get(consent_scope(settings, sid, pair['ticker'])) is True
            paused = paused or bool(rule and is_paused(settings, sid, pair['ticker'], rule.version))
            if tradable and paused:
                continue
            kind = "review_active" if tradable and evidence.get("review_active") else "new_match" if not tradable and evidence.get("qualified") else None
            if kind is None:
                continue
            key = f"{consent_scope(settings, sid, pair['ticker'])}:{kind}"
            if decisions.get(key) == evidence.get("fingerprint"):
                continue
            # Existing order evaluators have hard ticker guards. Outside the
            # native scope, research also uses a different contract profile.
            # Do not promise execution until a matching adapter is implemented.
            executable = bool(rule and not rule.observation_only and sid not in errors
                              and strategy['version'] == rule.version
                              and (not pair.get('research_contract_profile')
                                   or (rule.authored_exit_order_route and pair.get('research_contract_profile') == 'research_contracts_v1'))
                              and allowed_ticker(sid, pair['ticker'], rule)
                              and (sid not in PROTOCOLS or rule.authored_exit_order_route))
            live = bool(executable and (rule.authored_exit_order_route or review_live_promotion(rule, pair["ticker"]).ready))
            switch_on = bool(rule and settings.get(rule.setting_key, False))
            can_enable = executable and (switch_on or rule.authored_exit_order_route) and (paper or live)
            from strategy_health.closed_trade_guard import is_paused
            automatic_pause = bool(rule and is_paused(settings, sid, pair['ticker'], rule.version))
            can_enable = can_enable and not automatic_pause
            metrics = evidence["recent"] if kind == "review_active" else {**evidence["validation"], "option_results": evidence["independent_trades"]}
            result.append({
                "strategy_id": sid, "ticker": pair["ticker"], "strategy_version": strategy["version"],
                "display_name": strategy["display_name"], "kind": kind,
                "fingerprint": evidence["fingerprint"], "evidence": evidence,
                "profit_factor": metrics["profit_factor"], "completed_trades": metrics["option_results"],
                "net_pnl": metrics["net_one_contract_pnl"],
                "account_mode": "paper" if paper else "live", "can_enable": can_enable,
                "blocker": "Automatically moved to research only: actual closed-trade PF fell below 1 for this account and version." if automatic_pause else None if can_enable else "Research passed; the matching order-entry and exit route still needs implementation and review." if not executable else "Turn on the strategy switch before adding this ticker." if not switch_on and not rule.authored_exit_order_route else "Research passed; live execution review is still required.",
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
        from config.strategy_catalog import REVIEWED_STRATEGIES
        rule = REVIEWED_STRATEGIES[sid]
        if rule.authored_exit_order_route:
            updates[rule.setting_key] = True
        approvals = dict(settings.get("strategy_pair_approvals") or {})
        approvals[mode_key] = {"strategy_version": item["strategy_version"], "user_approved": True,
                               "strategy_id": sid, "ticker": ticker,
                               "evidence_fingerprint": fingerprint, "approved_at": datetime.now(timezone.utc).isoformat()}
        updates["strategy_pair_approvals"] = approvals
    decisions = dict(settings.get("strategy_pair_review_decisions") or {})
    decisions[f"{mode_key}:{item['kind']}"] = fingerprint
    updates["strategy_pair_review_decisions"] = decisions
    return updates
