"""
api/routes/trades.py — Trade journal and performance data.
"""
from __future__ import annotations
from fastapi import APIRouter, Query
from api.models import Trade, TradeListResponse, PerformanceStats, DailySummary

router = APIRouter(prefix="/api/trades", tags=["trades"])


def _row_to_trade(row: dict) -> Trade:
    return Trade(
        id=int(row.get("id", 0)),
        ticker=str(row.get("ticker", "")),
        direction=str(row.get("direction", "")),
        option_type=row.get("option_type"),
        strategy_id=row.get("strategy_id"),
        entry_price=float(row.get("entry_price", 0)),
        exit_price=float(row["exit_price"]) if row.get("exit_price") is not None else None,
        contracts=int(row.get("contracts", 0)),
        pnl=float(row["pnl"]) if row.get("pnl") is not None else None,
        status=str(row.get("status", "")),
        entry_time=str(row["entry_time"]) if row.get("entry_time") else None,
        exit_time=str(row["exit_time"]) if row.get("exit_time") else None,
        exit_reason=row.get("exit_reason"),
        stage1_done=bool(row.get("stage1_done", False)),
        mode=row.get("mode"),
    )


@router.get("", response_model=TradeListResponse)
def list_trades(
    mode: str = Query("paper", enum=["paper", "live"]),
    limit: int = Query(200, ge=1, le=1000),
    status: str = Query("all", enum=["all", "open", "closed"]),
) -> TradeListResponse:
    from database import get_all_trades
    rows = get_all_trades(limit=limit, mode=mode) or []

    if status == "open":
        rows = [r for r in rows if r.get("status") == "open"]
    elif status == "closed":
        rows = [r for r in rows if r.get("status") != "open"]

    trades = [_row_to_trade(r) for r in rows]
    closed = [t for t in trades if t.pnl is not None]
    total_pnl = sum(t.pnl for t in closed)
    wins = [t for t in closed if (t.pnl or 0) > 0]
    win_rate = len(wins) / len(closed) * 100 if closed else 0.0

    return TradeListResponse(
        trades=trades,
        total=len(trades),
        total_pnl=round(total_pnl, 2),
        win_rate=round(win_rate, 1),
    )


@router.get("/open", response_model=list[Trade])
def get_open_trades_endpoint() -> list[Trade]:
    from database import get_open_trades
    rows = get_open_trades() or []
    return [_row_to_trade(r) for r in rows]


@router.get("/performance", response_model=PerformanceStats)
def get_performance(mode: str = Query("paper")) -> PerformanceStats:
    from database import get_all_trades, get_daily_summaries
    rows = get_all_trades(limit=1000, mode=mode) or []
    closed = [r for r in rows if r.get("pnl") is not None]
    pnls = [float(r["pnl"]) for r in closed]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]

    # Daily summaries
    daily_raw = get_daily_summaries(mode=mode) or []
    daily = []
    for d in daily_raw:
        daily.append(DailySummary(
            date=str(d.get("date", "")),
            pnl=float(d.get("pnl", 0)),
            trades=int(d.get("trades", 0)),
            win_rate=float(d.get("win_rate", 0)),
        ))

    # Streak
    streak = 0
    for p in reversed(pnls):
        if p > 0:
            streak += 1
        else:
            break

    return PerformanceStats(
        total_pnl=round(sum(pnls), 2),
        total_trades=len(closed),
        win_rate=round(len(wins) / len(pnls) * 100 if pnls else 0, 1),
        avg_win=round(sum(wins) / len(wins) if wins else 0, 2),
        avg_loss=round(sum(losses) / len(losses) if losses else 0, 2),
        best_day=round(max((d.pnl for d in daily), default=0), 2),
        worst_day=round(min((d.pnl for d in daily), default=0), 2),
        current_streak=streak,
        daily_summaries=daily,
    )
