"""Short narration from actual permissions and evaluator results."""
import logging
from config.strategy_catalog import REVIEWED_STRATEGIES
from database import log_event

_REASONS = {
    "outside_validated_direction": "first break was down; this setup trades calls only",
    "waiting_for_impulse_pullback_reclaim": "waiting for a completed pullback and reclaim",
    "already_emitted": "Setup already recorded today",
    "outside_entry_window": "Outside this strategy's entry time",
    "entry_window_expired": "its entry time has passed",
    "armed_waiting_for_first_retouch": "waiting for price to revisit the breakout line",
    "building_or_waiting_for_breakout": "waiting for the first range break",
    "emitted": "setup already recorded today",
    "failed_retouch": "price failed the retouch",
    "data_check_failed": "Market-data check failed",
}
_LABELS = {"V2_ORB_PULLBACK": "ORB", "V2_TSLA_TWO_LEG_TREND_PULLBACK": "Two-leg"}


def scan_message(ticker, enabled, statuses, signals, *, coverage=None):
    eligible = [s for s in signals if s.strategy_id in enabled]
    if eligible:
        names = ", ".join(REVIEWED_STRATEGIES[s.strategy_id].display_name for s in eligible)
        return f"[{ticker}] Setup found: {names}. Checking order safeguards; no fill confirmed yet."
    if not enabled:
        return f"[{ticker}] Research only — no strategy is enabled to trade this ticker."
    evidence = (coverage or {}).get('strategies', {})
    failed = sorted(sid for sid in enabled if statuses.get(sid) == 'data_check_failed' or
                    evidence.get(sid, {}).get('evaluation') == 'evaluation_error' or
                    any(e.get('status') == 'post_evaluation_error' for e in evidence.get(sid, {}).get('events', [])))
    if failed:
        names = ', '.join(REVIEWED_STRATEGIES[sid].display_name if sid in REVIEWED_STRATEGIES else sid for sid in failed)
        return f"[{ticker}] No entry returned. Evaluation failed for {names}; this is not a no-setup result."
    blocked = sorted({r.get('routing') for r in evidence.values()
                      if r.get('routing') in {'kill_lock', 'conflict_veto', 'volume_roc_veto',
                                              'insufficient_input', 'empty_indicator_frame'}})
    if blocked:
        return f"[{ticker}] No entry returned. Router stopped at: {', '.join(blocked)}."
    reasons = list(dict.fromkeys(f"{_LABELS.get(key, key)}: {_REASONS[value]}"
                                for key, value in statuses.items()
                                if key in enabled and value in _REASONS))
    detail = "; ".join(reasons)
    return f"[{ticker}] Checked {len(enabled)} enabled strategies — no entry setup." + (f" {detail}." if detail else "")


def log_strategy_scan(state, ticker, enabled, statuses, signals, now, *, coverage=None):
    message = scan_message(ticker, enabled, statuses, signals, coverage=coverage)
    key = (now.strftime("%Y-%m-%dT%H:%M"), message)
    seen = state.setdefault("strategy_scan_messages", {})
    if seen.get(ticker) != key:
        seen[ticker] = key
        try:
            log_event("INFO", "bar_eval", message)
        except Exception:
            logging.getLogger('celo_trader.strategy_scan').debug('Scan narration unavailable', exc_info=True)
