"""
api/routes/trades.py — Trade journal and performance data.
"""
from __future__ import annotations
import json as _json
import logging
from datetime import date as _date
from fastapi import APIRouter, Query
from api.models import (
    Trade, TradeListResponse, PerformanceStats, DailySummary,
    TradeAnalytics, StrategyRow, HourRow, TickerRow, ExitReasonRow,
    AlpacaOrder, ReconcileRow, ReconcileResponse,
)

router = APIRouter(prefix="/api/trades", tags=["trades"])
logger = logging.getLogger("celo_trader.api.trades")


def _parse_annotations(raw: object) -> list[dict] | None:
    """
    Parse the trades.annotations_json column into a list of dicts for the
    API response. Never raises — a malformed/legacy blob (or the column
    being NULL on trades from before this feature existed) just means no
    annotations for this trade, not a broken Journal page.
    """
    if not raw:
        return None
    try:
        parsed = _json.loads(raw)
        return parsed if isinstance(parsed, list) else None
    except Exception:
        logger.warning("Malformed annotations_json on a trade row — returning no annotations", exc_info=True)
        return None


def _parse_mtf_bias(raw: object) -> dict | None:
    """Parse trades.mtf_bias_json the same defensive way as annotations above."""
    if not raw:
        return None
    try:
        parsed = _json.loads(raw)
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        logger.warning("Malformed mtf_bias_json on a trade row — returning no MTF data", exc_info=True)
        return None


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
        recap=row.get("recap"),
        annotations=_parse_annotations(row.get("annotations_json")),
        mtf_bias=_parse_mtf_bias(row.get("mtf_bias_json")),
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

    # Streak — positive = consecutive wins, negative = consecutive losses
    streak = 0
    for p in reversed(pnls):
        if p > 0:
            if streak >= 0:
                streak += 1
            else:
                break
        else:
            if streak <= 0:
                streak -= 1
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
    strat: dict = defaultdict(lambda: {
        "trades": 0, "wins": 0, "losses": 0,
        "total_pnl": 0.0, "win_pnl": 0.0, "loss_pnl": 0.0,
        "mfe_sum": 0.0, "mfe_count": 0,
    })
    for r in rows:
        sid  = r.get("strategy_id") or "UNKNOWN"
        pnl  = float(r.get("realized_pnl") or 0)
        strat[sid]["trades"]    += 1
        strat[sid]["total_pnl"] += pnl
        if pnl > 0:
            strat[sid]["wins"]    += 1
            strat[sid]["win_pnl"] += pnl
        elif pnl < 0:
            strat[sid]["losses"]    += 1
            strat[sid]["loss_pnl"]  += pnl
        # MFE only available for trades that stored peak_price
        if r.get("peak_price") is not None and float(r.get("entry_price") or 0) > 0:
            ep = float(r["entry_price"])
            strat[sid]["mfe_sum"]   += (float(r["peak_price"]) - ep) / ep * 100
            strat[sid]["mfe_count"] += 1

    by_strategy = [
        StrategyRow(
            strategy_id   = sid,
            trades        = v["trades"],
            wins          = v["wins"],
            losses        = v["losses"],
            win_rate      = round(v["wins"] / v["trades"] * 100, 1) if v["trades"] else 0.0,
            total_pnl     = round(v["total_pnl"], 2),
            avg_win       = round(v["win_pnl"]  / v["wins"],   2) if v["wins"]   else 0.0,
            avg_loss      = round(v["loss_pnl"] / v["losses"], 2) if v["losses"] else 0.0,
            profit_factor = round(v["win_pnl"] / abs(v["loss_pnl"]), 2) if v["loss_pnl"] else 0.0,
            avg_mfe_pct   = round(v["mfe_sum"] / v["mfe_count"], 1) if v["mfe_count"] else 0.0,
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
    tkr_data: dict = defaultdict(lambda: {
        "trades": 0, "wins": 0, "losses": 0,
        "pnl_sum": 0.0, "win_pnl": 0.0, "loss_pnl": 0.0,
    })
    for r in rows:
        t   = r.get("ticker") or "?"
        pnl = float(r.get("realized_pnl") or 0)
        tkr_data[t]["trades"]  += 1
        tkr_data[t]["pnl_sum"] += pnl
        if pnl > 0:
            tkr_data[t]["wins"]    += 1
            tkr_data[t]["win_pnl"] += pnl
        elif pnl < 0:
            tkr_data[t]["losses"]    += 1
            tkr_data[t]["loss_pnl"]  += pnl

    by_ticker = [
        TickerRow(
            ticker    = t,
            trades    = v["trades"],
            wins      = v["wins"],
            losses    = v["losses"],
            win_rate  = round(v["wins"] / v["trades"] * 100, 1) if v["trades"] else 0.0,
            total_pnl = round(v["pnl_sum"], 2),
            avg_win   = round(v["win_pnl"]  / v["wins"],   2) if v["wins"]   else 0.0,
            avg_loss  = round(v["loss_pnl"] / v["losses"], 2) if v["losses"] else 0.0,
        )
        for t, v in sorted(tkr_data.items(), key=lambda kv: -kv[1]["pnl_sum"])
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


# ── Reconcile endpoint ────────────────────────────────────────────────────────
# Compares bot DB trade records against actual Alpaca order fills for a given
# date. Highlights price gaps so the user can see the paper_fill discrepancy.

@router.get("/reconcile", response_model=ReconcileResponse)
def reconcile_trades(
    date: str = Query(default="", description="YYYY-MM-DD; defaults to today"),
) -> ReconcileResponse:
    import re
    from datetime import datetime, timezone, timedelta
    from database import get_all_trades
    from config import ALPACA_API_KEY, ALPACA_SECRET_KEY, ALPACA_BASE_URL, get_settings as _get_settings
    import requests as _req

    # ── 1. Resolve date ───────────────────────────────────────────────────────
    if not date or not re.match(r"\d{4}-\d{2}-\d{2}", date):
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    date_start = f"{date}T00:00:00Z"
    date_end   = f"{date}T23:59:59Z"

    # ── 2. Fetch Alpaca orders for the date ───────────────────────────────────
    headers = {
        "APCA-API-KEY-ID":     ALPACA_API_KEY,
        "APCA-API-SECRET-KEY": ALPACA_SECRET_KEY,
    }
    alpaca_orders: list[dict] = []
    try:
        resp = _req.get(
            f"{ALPACA_BASE_URL}/v2/orders",
            headers=headers,
            params={
                "status": "all",
                "after":  date_start,
                "until":  date_end,
                "limit":  500,
                "direction": "asc",
            },
            timeout=10,
        )
        resp.raise_for_status()
        alpaca_orders = resp.json() or []
    except Exception as _e:
        # Non-fatal — reconcile will still show DB data with empty Alpaca side
        alpaca_orders = []

    # ── 3. Fetch Alpaca equity ────────────────────────────────────────────────
    alpaca_equity: float | None = None
    try:
        acct = _req.get(
            f"{ALPACA_BASE_URL}/v2/account", headers=headers, timeout=5
        ).json()
        alpaca_equity = float(acct.get("equity", 0)) or None
    except Exception:
        pass

    # ── 4. Pull day_start_balance from settings ───────────────────────────────
    day_start_balance: float | None = None
    try:
        _cfg = _get_settings()
        dsb_key = f"day_start_{date}"
        raw_dsb = _cfg.get(dsb_key) or _cfg.get("day_start_balance")
        if raw_dsb is not None:
            day_start_balance = float(raw_dsb)
    except Exception:
        pass

    alpaca_session_pnl: float | None = (
        round(alpaca_equity - day_start_balance, 2)
        if alpaca_equity is not None and day_start_balance is not None
        else None
    )

    # ── 5. Pull DB trades for the date ────────────────────────────────────────
    all_db_rows = get_all_trades(limit=1000, mode="paper", status_filter="closed") or []
    db_trades = [
        r for r in all_db_rows
        if str(r.get("exit_time") or r.get("entry_time") or "").startswith(date)
    ]
    bot_session_pnl = round(
        sum(float(r.get("realized_pnl") or 0) for r in db_trades), 2
    )

    # ── 6. Build Alpaca order lookup: only FILLED orders, grouped by symbol ───
    # We keep buy fills and sell fills separately.
    # Each entry: {symbol -> [{"side", "filled_qty", "filled_avg_price", "filled_at", "order_id"}]}
    from collections import defaultdict
    alp_buys:  dict = defaultdict(list)
    alp_sells: dict = defaultdict(list)

    for o in alpaca_orders:
        if o.get("status") != "filled":
            continue
        sym   = o.get("symbol", "")
        side  = o.get("side", "")
        fqty  = int(float(o.get("filled_qty") or 0))
        fpx   = float(o.get("filled_avg_price") or 0) if o.get("filled_avg_price") else None
        fat   = o.get("filled_at") or o.get("submitted_at")
        oid   = o.get("id", "")
        entry = {"filled_qty": fqty, "filled_avg_price": fpx, "filled_at": fat, "order_id": oid}
        if side == "buy":
            alp_buys[sym].append(entry)
        else:
            alp_sells[sym].append(entry)

    # ── 7. Match DB trades to Alpaca fills ────────────────────────────────────
    # Strategy: for each DB trade, find the closest Alpaca buy + sell by contract_symbol.
    # We consume matched orders to avoid double-counting.
    used_buy_oids:  set[str] = set()
    used_sell_oids: set[str] = set()

    def _parse_ts(ts: str | None) -> datetime | None:
        if not ts:
            return None
        for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%fZ"):
            try:
                return datetime.strptime(ts[:26], fmt[:len(ts)])
            except Exception:
                pass
        try:
            return datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except Exception:
            return None

    reconcile_rows: list[ReconcileRow] = []
    matched_order_ids: set[str] = set()

    for r in db_trades:
        sym         = r.get("contract_symbol") or ""
        contracts   = int(r.get("contracts") or 1)
        bot_entry   = float(r.get("entry_price") or 0) or None
        bot_exit    = float(r.get("exit_price") or 0) or None
        bot_pnl     = float(r.get("realized_pnl") or 0)
        entry_time  = str(r.get("entry_time") or "")
        exit_time   = str(r.get("exit_time") or "")

        db_entry_ts = _parse_ts(entry_time)
        db_exit_ts  = _parse_ts(exit_time)

        # Find closest unused Alpaca buy for this symbol within ±60 min of entry
        alp_entry: float | None = None
        for ab in alp_buys.get(sym, []):
            if ab["order_id"] in used_buy_oids:
                continue
            ab_ts = _parse_ts(ab["filled_at"])
            if db_entry_ts and ab_ts:
                delta = abs((ab_ts - db_entry_ts).total_seconds())
                if delta > 3600:
                    continue
            alp_entry = ab.get("filled_avg_price")
            used_buy_oids.add(ab["order_id"])
            matched_order_ids.add(ab["order_id"])
            break

        # Find closest unused Alpaca sell for this symbol within ±60 min of exit
        alp_exit: float | None = None
        for ab in alp_sells.get(sym, []):
            if ab["order_id"] in used_sell_oids:
                continue
            ab_ts = _parse_ts(ab["filled_at"])
            if db_exit_ts and ab_ts:
                delta = abs((ab_ts - db_exit_ts).total_seconds())
                if delta > 3600:
                    continue
            alp_exit = ab.get("filled_avg_price")
            used_sell_oids.add(ab["order_id"])
            matched_order_ids.add(ab["order_id"])
            break

        # Compute actual Alpaca P&L for this leg
        alpaca_pnl: float | None = None
        if alp_entry is not None and alp_exit is not None:
            alpaca_pnl = round((alp_exit - alp_entry) * contracts * 100, 2)

        pnl_gap  = round(bot_pnl - alpaca_pnl, 2) if alpaca_pnl is not None else None
        has_gap  = abs(pnl_gap) > 1.0 if pnl_gap is not None else False

        reconcile_rows.append(ReconcileRow(
            trade_id        = int(r.get("id", 0)),
            ticker          = r.get("ticker"),
            strategy_id     = r.get("strategy_id"),
            contracts       = contracts,
            contract_symbol = sym,
            bot_entry       = bot_entry,
            bot_exit        = bot_exit,
            bot_pnl         = bot_pnl,
            entry_time      = entry_time or None,
            exit_time       = exit_time or None,
            alpaca_entry    = alp_entry,
            alpaca_exit     = alp_exit,
            alpaca_pnl      = alpaca_pnl,
            pnl_gap         = pnl_gap,
            has_gap         = has_gap,
        ))

    # ── 8. Collect unmatched Alpaca filled orders ─────────────────────────────
    unmatched: list[AlpacaOrder] = []
    for o in alpaca_orders:
        if o.get("status") != "filled":
            continue
        if o.get("id") in matched_order_ids:
            continue
        unmatched.append(AlpacaOrder(
            order_id        = o.get("id", ""),
            symbol          = o.get("symbol", ""),
            side            = o.get("side", ""),
            qty             = int(float(o.get("qty") or 0)),
            filled_qty      = int(float(o.get("filled_qty") or 0)),
            filled_avg_price= float(o.get("filled_avg_price") or 0) or None,
            status          = o.get("status", ""),
            submitted_at    = o.get("submitted_at"),
            filled_at       = o.get("filled_at"),
        ))

    equity_gap: float | None = (
        round(bot_session_pnl - alpaca_session_pnl, 2)
        if alpaca_session_pnl is not None
        else None
    )

    return ReconcileResponse(
        date                  = date,
        alpaca_equity         = alpaca_equity,
        day_start_balance     = day_start_balance,
        bot_session_pnl       = bot_session_pnl,
        alpaca_session_pnl    = alpaca_session_pnl,
        equity_gap            = equity_gap,
        trades                = reconcile_rows,
        unmatched_alpaca_orders = unmatched,
    )


# ── Alpaca actual daily P&L ───────────────────────────────────────────────────
# Queries Alpaca's portfolio history for REAL daily P&L (actual fills, not bot
# estimates). Used by the Performance calendar so it shows truth, not assumed fills.

@router.get("/alpaca-daily-pnl")
def get_alpaca_daily_pnl():
    """
    Returns daily P&L from Alpaca's portfolio/history endpoint.
    This is what the account ACTUALLY made/lost each day — distinct from the bot DB
    which uses paper_assumed_fill prices (mid at order time, not actual fill prices).
    Returns: list of {date: "YYYY-MM-DD", pnl: float}
    """
    from datetime import datetime
    import logging
    import requests as _req

    _log = logging.getLogger("celo_trader.api")

    try:
        from broker import AlpacaClient
        client = AlpacaClient()
        # portfolio/history: period=3M, daily bars, exclude extended hours
        resp = _req.get(
            f"{client.base}/v2/account/portfolio/history",
            headers=client.headers,
            params={"period": "3M", "timeframe": "1D", "extended_hours": "false"},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()

        timestamps  = data.get("timestamp") or []
        profit_loss = data.get("profit_loss") or []

        result = []
        for ts, pnl in zip(timestamps, profit_loss):
            if pnl is None:
                continue
            # Alpaca returns timestamps in UTC epoch seconds
            date_str = datetime.utcfromtimestamp(int(ts)).strftime("%Y-%m-%d")
            result.append({"date": date_str, "pnl": round(float(pnl), 2)})

        return result

    except Exception as e:
        _log.warning("alpaca_daily_pnl failed: %s", e)
        return []  # graceful fallback — frontend falls back to bot DB
