"""In-process, single-worker backtest jobs for the dashboard."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date as _date, datetime, timezone
import math
import threading
import time
from typing import Any
from uuid import uuid4

from api.models import BacktestRequest, BacktestResult

_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="backtest")
_jobs: dict[str, dict[str, Any]] = {}
_lock = threading.Lock()


def _to_result(req: BacktestRequest, progress_callback=None) -> BacktestResult:
    from broker import get_clients
    from backtester import Backtester

    start_date = None
    end_date = None
    months = req.months
    if req.start_date and req.end_date:
        try:
            start_date = _date.fromisoformat(req.start_date)
            end_date = _date.fromisoformat(req.end_date)
            months = max(1, math.ceil((end_date - start_date).days / 30))
        except ValueError:
            pass
    alpaca, _ = get_clients()
    backtester = Backtester(
        alpaca, req.ticker, months, req.starting_capital, req.direction, req.risk_pct,
        start_date=start_date, end_date=end_date,
    )
    backtester._progress_callback = progress_callback
    raw = backtester.run()
    if "error" in raw:
        return BacktestResult(
            total_return_pct=0, win_rate_pct=0, total_trades=0, avg_win=0,
            avg_loss=0, sharpe=0, max_drawdown_pct=0, final_balance=req.starting_capital,
            stage1_rate_pct=0, daily_pnl={}, exit_reasons={}, trades=[], error=raw["error"],
        )
    cap = req.starting_capital or 1.0
    return BacktestResult(
        total_return_pct=float(raw.get("total_return", 0)), win_rate_pct=float(raw.get("win_rate", 0)) * 100,
        total_trades=int(raw.get("total_trades", 0)), avg_win=float(raw.get("avg_win", 0)),
        avg_loss=float(raw.get("avg_loss", 0)), sharpe=float(raw.get("sharpe_ratio", 0)),
        max_drawdown_pct=float(raw.get("max_drawdown", 0)) / cap * 100,
        final_balance=float(raw.get("final_balance", cap)), stage1_rate_pct=float(raw.get("stage1_hit_rate", 0)),
        daily_pnl=raw.get("daily_pnl", {}), exit_reasons=raw.get("exit_reasons", {}), trades=raw.get("trades", []),
        call_trades=int(raw.get("call_trades", 0)), put_trades=int(raw.get("put_trades", 0)),
        call_win_rate=float(raw.get("call_win_rate", 0)), put_win_rate=float(raw.get("put_win_rate", 0)),
        call_pnl=float(raw.get("call_pnl", 0)), put_pnl=float(raw.get("put_pnl", 0)),
        strategy_breakdown=raw.get("strategy_breakdown", {}), model_fidelity=raw.get("model_fidelity", {}),
    )


def start(req: BacktestRequest) -> str:
    """Queue one replay; a single worker avoids competing with the paper bot."""
    job_id = uuid4().hex
    with _lock:
        _jobs[job_id] = {
            "status": "queued", "result": None, "error": None,
            "started_at": None, "completed_days": 0, "total_days": 0,
            "estimated_remaining_seconds": None,
        }

    def _work() -> None:
        started_monotonic = time.monotonic()
        with _lock:
            _jobs[job_id].update(status="running", started_at=datetime.now(timezone.utc).isoformat())

        def _progress(completed_days: int, total_days: int) -> None:
            elapsed = time.monotonic() - started_monotonic
            remaining = None
            if completed_days > 0 and total_days >= completed_days:
                remaining = round(elapsed / completed_days * (total_days - completed_days))
            with _lock:
                _jobs[job_id].update(
                    completed_days=completed_days,
                    total_days=total_days,
                    estimated_remaining_seconds=remaining,
                )
        try:
            result = _to_result(req, _progress)
            with _lock:
                _jobs[job_id].update(status="complete", result=result)
        except Exception as exc:
            with _lock:
                _jobs[job_id].update(status="failed", error=str(exc))

    _executor.submit(_work)
    return job_id


def get(job_id: str) -> dict[str, Any] | None:
    with _lock:
        job = _jobs.get(job_id)
        return dict(job) if job else None
