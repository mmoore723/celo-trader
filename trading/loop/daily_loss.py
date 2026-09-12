"""Testable daily-loss boundary around the single-writer execution batch."""
from risk.kill_lock import check_kill_lock
from trading.controls.panic import service_daily_loss_halt


def run_guarded_execution(*, risk, balance, balance_valid, collection_only,
                          broker, market, user_id, execute):
    """Research is submitted separately; only order-capable work is gated."""
    try:
        if balance_valid and not collection_only:
            risk.check_daily_loss(balance)
        if not collection_only:
            service_daily_loss_halt(broker, market, user_id=user_id)
        if balance_valid and not check_kill_lock()[0]:
            execute()
    finally:
        # Entry-denial returns, successful batches, and post-fill exceptions
        # must all service the same durable close request.
        if not collection_only:
            service_daily_loss_halt(broker, market, user_id=user_id)
