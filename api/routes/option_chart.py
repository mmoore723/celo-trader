"""Authenticated option-price history; reads only the current user's account."""
from datetime import datetime, timedelta, timezone
import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Request
from api.middleware.auth import require_auth

router = APIRouter(prefix="/api/trades", tags=["trades"], dependencies=[Depends(require_auth)])
logger = logging.getLogger("celo_trader.api.option_chart")


@router.get("/{trade_id}/option-chart")
def option_chart(request: Request, trade_id: int = Path(ge=1),
                 mode: Literal["paper", "live"] = "paper",
                 interval: Literal["1min", "daily"] = "1min") -> dict:
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
    result["interval"] = interval

    if interval == "daily" and result.get("entry_time") and result.get("contract_symbol"):
        try:
            from broker import get_tradier_market_client
            from api.option_chart_market import daily_option_candles
            now = datetime.fromtimestamp(result["as_of"], timezone.utc)
            start = datetime.fromtimestamp(result["entry_time"], timezone.utc) - timedelta(days=5)
            finish = min(now, datetime.fromtimestamp(result.get("exit_time") or result["as_of"], timezone.utc) + timedelta(days=5))
            result["window_start"], result["window_end"] = start.timestamp(), finish.timestamp()
            result["candles"] = daily_option_candles(get_tradier_market_client(), result["contract_symbol"], start, finish)
            if result["candles"]:
                result["candle_source"] = "tradier_history_daily"
        except Exception:
            logger.warning("Exact-contract daily candles unavailable", exc_info=True)

    # The chart uses real one-minute OHLCV from Tradier Time & Sales for the
    # exact OCC contract. Sampled bid/ask observations remain separate because
    # they are useful for executable P&L but are not market candles.
    if interval == "1min" and result.get("entry_time") and result.get("contract_symbol"):
        try:
            from broker import get_tradier_market_client
            entry = datetime.fromtimestamp(float(result["entry_time"]), timezone.utc)
            exit_or_now = datetime.fromtimestamp(
                min(float(result.get("exit_time") or result["as_of"]), float(result["as_of"])),
                timezone.utc,
            )
            start = entry - timedelta(minutes=20)
            finish = min(
                exit_or_now + (timedelta(minutes=20) if result.get("exit_time") else timedelta()),
                datetime.fromtimestamp(float(result["as_of"]), timezone.utc),
            )
            result["window_start"] = start.timestamp()
            result["window_end"] = finish.timestamp()
            raw_bars = get_tradier_market_client().get_option_bars(
                str(result["contract_symbol"]), start, finish, interval="1min",
            )
            result["candles"] = [
                {
                    "time": datetime.fromisoformat(str(bar["t"]).replace("Z", "+00:00")).timestamp(),
                    "open": float(bar["o"]), "high": float(bar["h"]),
                    "low": float(bar["l"]), "close": float(bar["c"]),
                    "volume": int(bar.get("v") or 0),
                }
                for bar in raw_bars
                if all(bar.get(key) is not None for key in ("t", "o", "h", "l", "c"))
            ]
            if result["candles"]:
                result["candle_source"] = "tradier_timesales_1min"
        except Exception:
            # Quote history and fills still render honestly when an expired
            # contract or a temporary market-data failure has no OHLC history.
            logger.warning("Exact-contract one-minute candles unavailable", exc_info=True)
    if not result["closed"] and result.get("contract_symbol"):
        try:
            from broker import get_tradier_market_client
            from api.option_chart_market import current_option_bid
            quote = current_option_bid(get_tradier_market_client(), result["contract_symbol"], datetime.now(timezone.utc).timestamp())
            if quote and quote["time"] >= (result.get("entry_time") or 0) and (
                not result["quotes"] or quote["time"] > result["quotes"][-1]["time"]
            ):
                result["quotes"].append(quote)
        except Exception:
            logger.warning("Current option chart quote unavailable", exc_info=True)
    return result
