"""Authenticated option-price history; reads only the current user's account."""
import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Request
from api.middleware.auth import require_auth

router = APIRouter(prefix="/api/trades", tags=["trades"], dependencies=[Depends(require_auth)])
logger = logging.getLogger("celo_trader.api.option_chart")


@router.get("/{trade_id}/option-chart")
def option_chart(request: Request, trade_id: int = Path(ge=1),
                 mode: Literal["paper", "live"] = "paper") -> dict:
    from config import get_settings
    from config.paths import get_user_data_dir
    from database.option_chart import read_option_chart

    if not getattr(request.state, "user_id", None):
        raise HTTPException(401, "Not authenticated")
    settings = get_settings()
    account_id = settings.get("active_broker_account_id")
    if not account_id:
        raise HTTPException(404, "No connected account")
    try:
        result = read_option_chart(
            get_user_data_dir(create=False) / f"trades_{mode}.db",
            trade_id=trade_id, account_id=account_id, paper=mode == "paper",
        )
    except Exception:
        logger.exception("Option chart read failed")
        raise HTTPException(503, "Option prices could not be loaded. Try again.") from None
    if result is None:
        raise HTTPException(404, "Trade not found in this account")
    return result
