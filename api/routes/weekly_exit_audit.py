"""Authenticated, read-only access to precomputed audit metadata."""
from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api/weekly-exit-audits", tags=["weekly-exit-audits"])


def scope():
    from config import get_settings
    from config.paths import get_user_data_dir
    settings = get_settings()
    return (get_user_data_dir(create=False)/"weekly_exit_audits.sqlite3",
            settings.get("active_broker_account_id"),
            "paper" if settings.get("paper_trading", True) else "live")


@router.get("")
def latest():
    from strategy_health.weekly_exit_audit.store import read
    return {"audits": read(*scope())}


@router.get("/{audit_id}")
def detail(audit_id: int):
    from strategy_health.weekly_exit_audit.store import read
    result = read(*scope(), audit_id=audit_id)
    if result is None:
        raise HTTPException(404, "Audit not found for this account")
    return result
