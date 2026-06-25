"""
api/routes/backtest.py — Run historical backtests.
"""
from __future__ import annotations
from fastapi import APIRouter, HTTPException
from api.models import BacktestRequest, BacktestResult

router = APIRouter(prefix="/api/backtest", tags=["backtest"])


@router.post("", response_model=BacktestResult)
def run_backtest(req: BacktestRequest) -> BacktestResult:
    try:
        from broker import get_clients
        from backtester import Backtester
        alpaca, _ = get_clients()
        bt = Backtester(
            alpaca=alpaca,
            ticker=req.ticker,
            months=req.months,
            starting_capital=req.starting_capital,
            direction=req.direction,
        )
        res = bt.run()
        if "error" in res:
            return BacktestResult(
                total_return_pct=0, win_rate_pct=0, total_trades=0,
                avg_win=0, avg_loss=0, sharpe=0, max_drawdown_pct=0,
                final_balance=req.starting_capital, stage1_rate_pct=0,
                daily_pnl={}, exit_reasons={}, trades=[],
                error=res["error"],
            )

        # Key mapping: backtester returns raw names; model expects _pct suffixes.
        # win_rate is a ratio (0.0–1.0) → multiply by 100 for display.
        # max_drawdown is in dollars → convert to % of starting capital.
        cap = req.starting_capital or 1.0
        return BacktestResult(
            total_return_pct = float(res.get("total_return", 0)),
            win_rate_pct     = float(res.get("win_rate", 0)) * 100,
            total_trades     = int(res.get("total_trades", 0)),
            avg_win          = float(res.get("avg_win", 0)),
            avg_loss         = float(res.get("avg_loss", 0)),
            sharpe           = float(res.get("sharpe_ratio", 0)),
            max_drawdown_pct = float(res.get("max_drawdown", 0)) / cap * 100,
            final_balance    = float(res.get("final_balance", cap)),
            stage1_rate_pct  = float(res.get("stage1_hit_rate", 0)),
            daily_pnl        = res.get("daily_pnl", {}),
            exit_reasons     = res.get("exit_reasons", {}),
            trades           = res.get("trades", []),
            call_trades      = int(res.get("call_trades", 0)),
            put_trades       = int(res.get("put_trades", 0)),
            call_win_rate    = float(res.get("call_win_rate", 0)),
            put_win_rate     = float(res.get("put_win_rate", 0)),
            call_pnl           = float(res.get("call_pnl", 0)),
            put_pnl            = float(res.get("put_pnl", 0)),
            strategy_breakdown = res.get("strategy_breakdown", {}),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
