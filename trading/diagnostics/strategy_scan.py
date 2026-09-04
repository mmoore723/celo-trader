"""Short narration from actual permissions and evaluator results."""
from config.strategy_catalog import REVIEWED_STRATEGIES
from database import log_event

_REASONS = {
    "outside_validated_direction": "ORB: first break was down; this setup trades calls only",
    "waiting_for_impulse_pullback_reclaim": "Two-leg: waiting for a completed pullback and reclaim",
    "already_emitted": "Setup already recorded today",
    "outside_entry_window": "Outside this strategy's entry time",
    "entry_window_expired": "ORB: its entry time has passed",
    "armed_waiting_for_first_retouch": "ORB: waiting for price to revisit the breakout line",
    "building_or_waiting_for_breakout": "ORB: waiting for the first range break",
    "emitted": "ORB: setup already recorded today",
    "failed_retouch": "ORB: price failed the retouch",
    "data_check_failed": "Market-data check failed",
}


def scan_message(ticker, enabled, statuses, signals):
    eligible = [s for s in signals if s.strategy_id in enabled]
    if eligible:
        names = ", ".join(REVIEWED_STRATEGIES[s.strategy_id].display_name for s in eligible)
        return f"[{ticker}] Setup found: {names}. Checking order safeguards; no fill confirmed yet."
    if not enabled:
        return f"[{ticker}] Research only — no strategy is enabled to trade this ticker."
    reasons = list(dict.fromkeys(_REASONS[value] for key, value in statuses.items()
                                if key in enabled and value in _REASONS))
    detail = "; ".join(reasons)
    return f"[{ticker}] Checked {len(enabled)} enabled strategies — no entry setup." + (f" {detail}." if detail else "")


def log_strategy_scan(state, ticker, enabled, statuses, signals, now):
    message = scan_message(ticker, enabled, statuses, signals)
    key = (now.strftime("%Y-%m-%dT%H:%M"), message)
    seen = state.setdefault("strategy_scan_messages", {})
    if seen.get(ticker) != key:
        seen[ticker] = key
        log_event("INFO", "bar_eval", message)
