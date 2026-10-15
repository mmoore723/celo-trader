import math

from risk.kill_lock import check_kill_lock, flatten_pending, clear_kill_lock, _lock_path


def halt_status():
    locked, reason = check_kill_lock()
    try:
        pending = flatten_pending()
    except Exception:
        pending = True
    return {"halted": locked, "reason": reason, "close_pending": pending,
            "scope": _lock_path().name}


def resume_after_review(broker, *, day_start, settings, realized):
    if not check_kill_lock()[0]:
        return
    if flatten_pending():
        raise ValueError("Exit fills must be confirmed before resuming.")
    from database import get_open_trades, log_event
    if get_open_trades() or broker.get_positions() or broker.get_open_orders():
        raise ValueError("Positions or orders remain unresolved. Reconcile before resuming.")
    account = broker.get_account()
    if account.get("trading_blocked") or account.get("account_blocked"):
        raise ValueError("The broker still blocks trading on this account.")
    equity = float(account["equity"])
    base = float(day_start)
    hard = float(settings["daily_loss_hard_cap_pct"]) / 100
    soft = float(settings["max_daily_loss_pct"])
    if not all(math.isfinite(x) for x in (equity, base, hard, soft, realized)) or base <= 0 or equity < 0:
        raise ValueError("Cannot verify current equity and daily loss allowance.")
    if not 0 < hard <= 1 or not 0 < soft <= 1:
        raise ValueError("Invalid daily loss limits.")
    if equity - base <= -base * hard or realized <= -base * min(hard, soft):
        raise ValueError("The daily loss limit is still breached. Resume does not reset or override your limits.")
    log_event("WARNING", "risk", f"User requested resume: equity={equity:.2f}, day-open={base:.2f}, realized={realized:.2f}; limits unchanged")
    clear_kill_lock()
    if check_kill_lock()[0]:
        raise ValueError("Another halt remains active. Trading has not resumed.")
