"""
trading/loop/audits.py — Once-per-day / once-per-week background triggers
for the strategy health audit and weekly review, fired from the after-hours
branch of the main trading loop.

Split out of the old single trading/loop.py (2026-08-01, file-size cleanup);
no logic changed, only relocated.
"""

import logging

from trading.state import _now_et

logger = logging.getLogger("celo_trader.trading_logic")


def _run_nightly_strategy_audit_once(alpaca) -> None:
    """
    Trigger the built-in strategy health audit (strategy_health/runner.py)
    once per calendar day, right as the bot enters after-hours sleep.
    Runs in a background thread so a slow audit never delays the deep-sleep
    loop or blocks Stop Bot from responding. Deduped via a saved settings
    key so a mid-evening bot restart doesn't re-run the same day's audit.
    """
    import threading
    from config import get_settings, save_settings

    today_str = _now_et().date().isoformat()
    if get_settings().get("last_strategy_audit_date") == today_str:
        return   # already ran today

    def _worker() -> None:
        try:
            from strategy_health.runner import run_daily_audit
            from database import log_event as _le
            run_daily_audit(alpaca)
            save_settings({"last_strategy_audit_date": today_str})
            _le("INFO", "trading_logic", "📊 Nightly strategy audit complete — see Strategy Operations.")
        except Exception as exc:
            logger.warning("Nightly strategy audit failed (non-fatal): %s", exc)

    threading.Thread(target=_worker, daemon=True, name="strategy-health-audit").start()


def _run_weekly_strategy_review_once(alpaca) -> None:
    """
    Trigger the weekly strategy review (strategy_health/runner.py::
    run_weekly_review) once per ISO week, on Fridays only, right alongside
    the daily audit above. Deduped via a saved settings key on the ISO
    year-week (e.g. "2026-W29") so a mid-evening restart doesn't re-run the
    same week. `alpaca` isn't actually used by the weekly review (it only
    reads already-saved daily audits + the trades table, no market-data
    fetch) but is accepted for symmetry with the daily trigger's call site.
    """
    import threading
    from config import get_settings, save_settings

    today = _now_et().date()
    if today.weekday() != 4:   # 0=Monday .. 4=Friday
        return

    week_label = f"{today.isocalendar()[0]}-W{today.isocalendar()[1]:02d}"
    if get_settings().get("last_weekly_review_week") == week_label:
        return   # already ran this week

    def _worker() -> None:
        try:
            from strategy_health.runner import run_weekly_review
            from database import log_event as _le
            run_weekly_review()
            save_settings({"last_weekly_review_week": week_label})
            _le("INFO", "trading_logic", "📈 Weekly strategy review complete — see Strategy Operations.")
        except Exception as exc:
            logger.warning("Weekly strategy review failed (non-fatal): %s", exc)

    threading.Thread(target=_worker, daemon=True, name="strategy-health-weekly").start()
