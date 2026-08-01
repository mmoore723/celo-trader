"""Non-blocking historical backtest endpoints."""
from fastapi import APIRouter, HTTPException

from api import backtest_jobs
from api.models import BacktestJobStatus, BacktestRequest

router = APIRouter(prefix="/api/backtest", tags=["backtest"])


@router.post("", response_model=BacktestJobStatus)
def start_backtest(req: BacktestRequest) -> BacktestJobStatus:
    job_id = backtest_jobs.start(req)
    return BacktestJobStatus(job_id=job_id, status="queued")


@router.get("/{job_id}", response_model=BacktestJobStatus)
def get_backtest(job_id: str) -> BacktestJobStatus:
    job = backtest_jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Backtest job not found or server restarted")
    return BacktestJobStatus(job_id=job_id, **job)
