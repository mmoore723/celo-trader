"""
api/routes/trades.py — Trade journal and performance data.
"""
from __future__ import annotations
from fastapi import APIRouter, Query
from api.models import (
    Trade, TradeListResponse, PerformanceStats, DailySummary,
    TradeAnalytics, StrategyRow, HourRow, TickerRow, ExitReasonRow,
)

router = APIRouter(prefix="/api/trades", tags=["trades"])


def _row_to_trade(row: dict) -> Trade:
    # DB stores 'realized_pnl' not 'pnl'; 'paper' int not 'mode' string;
    # 'direction' doesn't exist — derive from option_type.
    opt_type  = row.get("option_type") or ""
    direction = "long" if opt_type.lower() == "call" else "short" if opt_type.lower() == "put" else "long"
    mode      = "paper" if int(row.get("paper", 1)) else "live"
    pnl_raw   = row.get("realized_pnl") if row.get("realized_pnl") is not None else row.get("pnl")
    entry_px  = float(row.get("entry_price", 0)) or 0
    exit_px   = float(row["exit_price"])  if row.get("exit_price")  is not None else None
    peak_px   = float(row["peak_price"])  if row.get("peak_price")  is not None else None
    mae_px    = float(row["mae_price"])   if row.get("mae_price")   is not None else None

    # Compute MFE %, MAE %, and exit efficiency — all derived fields shown in the Journal.
    # mfe_pct:            how much the option appreciated from entry to its peak.
    # mae_pct:            how far the option dropped below entry (negative = adverse).
    # exit_efficiency_pct: what fraction of the peak-to-entry move you actually captured.
    #                      100% = you exited exactly at the peak; 0% = exited at entry.
    mfe_pct = mae_pct = exit_efficiency_pct = None
    if peak_px is not None and entry_px > 0:
        mfe_pct = round((peak_px - entry_px) / entry_px * 100, 1)
        if exit_px is not None and (peak_px - entry_px) > 0:
            exit_efficiency_pct = round(
                max(0.0, (exit_px - entry_px) / (peak_px - entry_px)) * 100, 1
            )
    if mae_px is not None and entry_px > 0:
        mae_pct = round((mae_px - entry_px) / entry_px * 100, 1)

    return Trade(
        id=int(row.get("id", 0)),
        ticker=str(row.get("ticker", "")),
        direction=direction,
        option_type=opt_type or None,
        strategy_id=row.get("strategy_id"),
        contract_symbol=row.get("contract_symbol"),
        strike=float(row["strike"]) if row.get("strike") is not None else None,
        expiry=row.get("expiry"),
        entry_price=entry_px,
        exit_price=exit_px,
        stop_price=float(row["stop_price"]) if row.get("stop_price") is not None else None,
        target_price=float(row["target_price"]) if row.get("target_price") is not None else None,
        peak_price=peak_px,
        mae_price=mae_px,
        mfe_pct=mfe_pct,
        mae_pct=mae_pct,
        exit_efficiency_pct=exit_efficiency_pct,
        contracts=int(row.get("contracts", 0)),
        pnl=float(pnl_raw) if pnl_raw is not None else None,
        status=str(row.get("status", "")),
        entry_time=str(row["entry_time"]) if row.get("entry_time") else None,
        exit_time=str(row["exit_time"]) if row.get("exit_time") else None,
        exit_reason=row.get("exit_reason"),
        stage1_done=bool(row.get("stage1_done", False)),
        mode=mode,
    )


@router.get("", response_model=TradeListResponse)
def list_trades(
    mode: str = Query("paper", enum=["paper", "live"]),
    limit: int = Query(200, ge=1, le=1000),
    status: str = Query("all", enum=["all", "open", "closed"]),
) -> TradeListResponse:
    from database import get_all_trades
    rows = get_all_trades(limit=limit, mode=mode, status_filter=status) or []

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
    closed = [r for r in rows if r.get("realized_pnl") is not None or r.get("pnl") is not None]
    pnls = [float(r.get("realized_pnl") or r.get("pnl") or 0) for r in closed]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]

    # Daily summaries
    daily_raw = get_daily_summaries(mode=mode) or []
    daily = []
    for d in daily_raw:
        daily.append(DailySummary(
            date=str(d.get("trade_date") or d.get("date", "")),
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


@router.get("/analytics", response_model=TradeAnalytics)
def get_analytics(mode: str = Query("paper")) -> TradeAnalytics:
    """
    Compute win rate breakdowns by strategy, time-of-day, ticker, and exit reason.
    Also computes average MFE%, average exit%, and average exit efficiency%.
    All values derived from closed trades only.
    """
    from collections import defaultdict
    from database import get_all_trades

    rows = get_all_trades(limit=2000, mode=mode, status_filter="closed") or []

    # ── By strategy ───────────────────────────────────────────────────────────
    strat: dict = defaultdict(lambda: {"trades": 0, "wins": 0, "total_pnl": 0.0, "mfe_sum": 0.0, "mfe_count": 0})
    for r in rows:
        sid  = r.get("strategy_id") or "UNKNOWN"
        pnl  = float(r.get("realized_pnl") or 0)
        strat[sid]["trades"]    += 1
        strat[sid]["total_pnl"] += pnl
        if pnl > 0:
            strat[sid]["wins"] += 1
        # MFE only available for trades that stored peak_price
        if r.get("peak_price") is not None and float(r.get("entry_price") or 0) > 0:
            ep = float(r["entry_price"])
            strat[sid]["mfe_sum"]   += (float(r["peak_price"]) - ep) / ep * 100
            strat[sid]["mfe_count"] += 1

    by_strategy = [
        StrategyRow(
            strategy_id = sid,
            trades      = v["trades"],
            wins        = v["wins"],
            win_rate    = round(v["wins"] / v["trades"] * 100, 1) if v["trades"] else 0.0,
            total_pnl   = round(v["total_pnl"], 2),
            avg_mfe_pct = round(v["mfe_sum"] / v["mfe_count"], 1) if v["mfe_count"] else 0.0,
        )
        for sid, v in sorted(strat.items(), key=lambda kv: -kv[1]["total_pnl"])
    ]

    # ── By hour of entry ──────────────────────────────────────────────────────
    hour_data: dict = defaultdict(lambda: {"trades": 0, "wins": 0, "pnl_sum": 0.0})
    for r in rows:
        et  = str(r.get("entry_time") or "")
        pnl = float(r.get("realized_pnl") or 0)
        # entry_time is "YYYY-MM-DD HH:MM:SS" format
        if len(et) >= 13:
            try:
                h = int(et[11:13])
                hour_data[h]["trades"]  += 1
                hour_data[h]["pnl_sum"] += pnl
                if pnl > 0:
                    hour_data[h]["wins"] += 1
            except (ValueError, IndexError):
                pass

    by_hour = [
        HourRow(
            hour     = h,
            label    = f"{h}:00",
            trades   = v["trades"],
            wins     = v["wins"],
            win_rate = round(v["wins"] / v["trades"] * 100, 1) if v["trades"] else 0.0,
            avg_pnl  = round(v["pnl_sum"] / v["trades"], 2) if v["trades"] else 0.0,
        )
        for h, v in sorted(hour_data.items())
    ]

    # ── By ticker ─────────────────────────────────────────────────────────────
    tkr_data: dict = defaultdict(lambda: {"trades": 0, "wins": 0, "pnl_sum": 0.0})
    for r in rows:
        t   = r.get("ticker") or "?"
        pnl = float(r.get("realized_pnl") or 0)
        tkr_data[t]["trades"]  += 1
        tkr_data[t]["pnl_sum"] += pnl
        if pnl > 0:
            tkr_data[t]["wins"] += 1

    by_ticker = [
        TickerRow(
            ticker   = t,
            trades   = v["trades"],
            wins     = v["wins"],
            win_rate = round(v["wins"] / v["trades"] * 100, 1) if v["trades"] else 0.0,
            total_pnl= round(v["pnl_sum"], 2),
        )
        for t, v in sorted(tkr_data.items(), key=lambda kv: -abs(kv[1]["pnl_sum"]))
    ]

    # ── By exit reason ────────────────────────────────────────────────────────
    exit_data: dict = defaultdict(lambda: {"trades": 0, "pnl_sum": 0.0})
    for r in rows:
        reason = r.get("exit_reason") or "unknown"
        pnl    = float(r.get("realized_pnl") or 0)
        exit_data[reason]["trades"]  += 1
        exit_data[reason]["pnl_sum"] += pnl

    by_exit_reason = [
        ExitReasonRow(
            reason    = reason,
            trades    = v["trades"],
            total_pnl = round(v["pnl_sum"], 2),
            avg_pnl   = round(v["pnl_sum"] / v["trades"], 2) if v["trades"] else 0.0,
        )
        for reason, v in sorted(exit_data.items(), key=lambda kv: kv[1]["pnl_sum"])
    ]

    # ── Portfolio-level averages ──────────────────────────────────────────────
    mfe_vals, exit_vals, eff_vals = [], [], []
    for r in rows:
        ep = float(r.get("entry_price") or 0)
        if ep <= 0:
            continue
        xp = r.get("exit_price")
        pp = r.get("peak_price")
        if xp is not None:
            exit_vals.append((float(xp) - ep) / ep * 100)
        if pp is not None:
            mfe_vals.append((float(pp) - ep) / ep * 100)
            if xp is not None and (float(pp) - ep) > 0:
                eff_vals.append(
                    max(0.0, (float(xp) - ep) / (float(pp) - ep)) * 100
                )

    avg_mfe_pct           = round(sum(mfe_vals)  / len(mfe_vals)  if mfe_vals  else 0.0, 1)
    avg_exit_pct          = round(sum(exit_vals) / len(exit_vals) if exit_vals else 0.0, 1)
    avg_exit_efficiency   = round(sum(eff_vals)  / len(eff_vals)  if eff_vals  else 0.0, 1)

    return TradeAnalytics(
        by_strategy              = by_strategy,
        by_hour                  = by_hour,
        by_ticker                = by_ticker,
        by_exit_reason           = by_exit_reason,
        avg_mfe_pct              = avg_mfe_pct,
        avg_exit_pct             = avg_exit_pct,
        avg_exit_efficiency_pct  = avg_exit_efficiency,
    )
