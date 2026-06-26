"""
api/routes/market.py — Market data: bars, quotes, scanner results.
"""
from __future__ import annotations
from datetime import datetime
import pytz
from fastapi import APIRouter, HTTPException, Query
from api.models import Bar, Quote, ScannerResult

router = APIRouter(prefix="/api/market", tags=["market"])

_ET = pytz.timezone("America/New_York")


def _market_is_open() -> bool:
    """
    True only during regular market hours (9:30–16:00 ET, Mon–Fri).
    Alpaca's free IEX tier returns NO data outside this window, so
    callers can skip the Alpaca call entirely when this is False.
    """
    now = datetime.now(_ET)
    if now.weekday() >= 5:          # Saturday=5, Sunday=6
        return False
    hm = now.hour * 60 + now.minute
    return 9 * 60 + 30 <= hm < 16 * 60


@router.get("/bars/{ticker}", response_model=list[Bar])
def get_bars(
    ticker: str,
    timeframe: str = Query("5Min", enum=["1Min", "5Min", "15Min", "1Hour"]),
    limit: int = Query(200, ge=10, le=1000),
) -> list[Bar]:
    """
    Fetch OHLCV bars with pre/after-market data.

    Attempt 1: Alpaca IEX — ONLY during regular market hours (9:30–16:00 ET).
               Alpaca's free IEX tier returns nothing outside that window, so
               we skip it entirely when the market is closed to avoid noisy
               failed-request logs in the Bot Thinking panel.
    Attempt 2: yfinance with prepost=True — covers 4 AM–8 PM ET, always tried
               when market is closed or Alpaca returns empty.
    """
    import pandas as pd
    from signals import bars_to_df, compute_vwap, compute_vwap_bands, compute_rvol, compute_atr

    df = pd.DataFrame()

    # ── Attempt 1: Alpaca — skip entirely when market is closed ──────────────
    if _market_is_open():
        try:
            from broker import get_clients
            alpaca, _ = get_clients()
            raw  = alpaca.get_bars(ticker, timeframe, limit=limit)
            bars = raw[0] if isinstance(raw, tuple) else raw
            if bars:
                df = bars_to_df(bars)
        except Exception:
            pass  # fall through to yfinance

    # ── Attempt 2: yfinance (pre/after-market, no quota) ─────────────────────
    if df.empty:
        try:
            import yfinance as yf
            import datetime as _dt
            import concurrent.futures
            # Map our timeframe strings to yfinance intervals
            _yf_interval = {"1Min": "1m", "5Min": "5m", "15Min": "15m", "1Hour": "60m"}.get(timeframe, "5m")
            # Use explicit start/end dates instead of period= to bypass yfinance's
            # filesystem cache, which can return stale data from a prior session.
            # 1m bars: yfinance max is 7 days; 5m/15m/60m: use 30 days (enough for
            # 500 bars and avoids the 60-day stale-cache issue we've seen in prod).
            _today      = _dt.date.today()
            _lookback   = 6 if _yf_interval == "1m" else 30
            _start_date = (_today - _dt.timedelta(days=_lookback)).strftime("%Y-%m-%d")
            _end_date   = (_today + _dt.timedelta(days=1)).strftime("%Y-%m-%d")
            # Wrap yf.download in a thread with a 15-second timeout.
            # Without this, Yahoo Finance network hangs block the FastAPI thread
            # indefinitely → the browser spins forever and the chart stays blank.
            def _yf_fetch():
                return yf.download(
                    ticker,
                    start=_start_date,
                    end=_end_date,
                    interval=_yf_interval,
                    prepost=True,
                    progress=False,
                    auto_adjust=True,
                )
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as _ex:
                _fut = _ex.submit(_yf_fetch)
                try:
                    raw_yf = _fut.result(timeout=15)
                except concurrent.futures.TimeoutError:
                    raw_yf = pd.DataFrame()
            if not raw_yf.empty:
                # Flatten MultiIndex columns produced by yfinance ≥ 0.2
                if hasattr(raw_yf.columns, "get_level_values"):
                    raw_yf.columns = raw_yf.columns.get_level_values(0)
                raw_yf = raw_yf.rename(columns={
                    "Open": "open", "High": "high",
                    "Low": "low",  "Close": "close", "Volume": "volume",
                })
                raw_yf.index.name = "time"
                raw_yf = raw_yf.reset_index()
                # Convert tz-aware index to ET naive (matches rest of pipeline)
                raw_yf["time"] = (
                    pd.to_datetime(raw_yf["time"], utc=True)
                    .dt.tz_convert("America/New_York")
                    .dt.tz_localize(None)
                )
                raw_yf = raw_yf[["time","open","high","low","close","volume"]].copy()
                # Drop bad thin-market prints: bars where close moved >8% from
                # the prior bar's close are almost always erroneous pre/post
                # market data (single-trade bad prints in illiquid sessions).
                prev_close = raw_yf["close"].shift(1)
                pct_move   = (raw_yf["close"] - prev_close).abs() / prev_close
                raw_yf     = raw_yf[(pct_move < 0.08) | pct_move.isna()].reset_index(drop=True)
                df = raw_yf.tail(limit).reset_index(drop=True)
        except Exception:
            pass

    if df.empty:
        raise HTTPException(status_code=503, detail=f"No bar data available for {ticker} from Alpaca or yfinance")

    df["rvol"] = compute_rvol(df)
    df["atr"]  = compute_atr(df)
    # compute_vwap_bands returns a df with vwap, vwap_upper1/2, vwap_lower1/2
    bands_df = compute_vwap_bands(df)
    for col in ("vwap", "vwap_upper1", "vwap_lower1", "vwap_upper2", "vwap_lower2"):
        df[col] = bands_df[col] if col in bands_df.columns else None

    def _f(row: pd.Series, col: str):
        v = row.get(col)
        return float(v) if v is not None and pd.notna(v) else None

    result = []
    for _, row in df.iterrows():
        t = row["time"]
        result.append(Bar(
            time=str(t.isoformat() if hasattr(t, "isoformat") else t),
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            volume=float(row.get("volume", 0)),
            vwap=        _f(row, "vwap"),
            vwap_upper1= _f(row, "vwap_upper1"),
            vwap_lower1= _f(row, "vwap_lower1"),
            vwap_upper2= _f(row, "vwap_upper2"),
            vwap_lower2= _f(row, "vwap_lower2"),
            rvol=        _f(row, "rvol"),
            atr=         _f(row, "atr"),
        ))
    return result


@router.get("/quotes", response_model=list[Quote])
def get_quotes(
    tickers: str = Query("SPY,QQQ,AAPL,NVDA,TSLA"),
) -> list[Quote]:
    try:
        from broker import get_clients
        alpaca, _ = get_clients()
        symbol_list = [t.strip().upper() for t in tickers.split(",")]
        snaps = alpaca.get_snapshots(symbol_list)
        result = []
        for sym, snap in (snaps or {}).items():
            # broker.get_snapshots() already processes raw Alpaca data into flat fields
            price      = float(snap.get("price", 0) or 0)
            change_pct = float(snap.get("change_pct", 0) or 0)
            vol        = float(snap.get("daily_vol", 0) or 0)
            result.append(Quote(
                ticker=sym,
                price=price,
                change_pct=round(change_pct, 2),
                volume=vol,
            ))
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _fetch_live_prices(tickers: list[str]) -> dict[str, float]:
    """
    Fetch current prices from Alpaca snapshots for a list of tickers.
    Returns a dict {ticker: price}.  Safe to call with an empty list.
    """
    if not tickers:
        return {}
    try:
        from broker import get_clients
        alpaca, _ = get_clients()
        snaps = alpaca.get_snapshots(tickers) or {}
        return {sym: float(snap.get("price", 0) or 0) for sym, snap in snaps.items()}
    except Exception:
        return {}


@router.get("/scanner", response_model=list[ScannerResult])
def get_scanner() -> list[ScannerResult]:
    """
    Returns today's premarket scan results.

    Reads from daily_universe.json (scan_details) which stores full per-ticker
    metrics (rvol, price, atr, gap_pct, score).  Falls back to scanner_state.json
    if daily_universe.json is missing or stale.  scanner_state.json watchlist is a
    plain list of strings — never call .get() on the items directly.

    If scan data is from a prior session (date mismatch) or prices are zero,
    live prices are fetched from Alpaca snapshots before returning.
    """
    try:
        import json
        import datetime as _dt
        from pathlib import Path

        base          = Path(__file__).resolve().parents[2]
        universe_path = base / "daily_universe.json"
        state_path    = base / "scanner_state.json"
        today_str     = _dt.date.today().isoformat()
        results: list[ScannerResult] = []

        # ── Preferred source: daily_universe.json has rich per-ticker dicts ──
        if universe_path.exists():
            u = json.loads(universe_path.read_text())
            details = u.get("scan_details", [])
            for i, d in enumerate(details[:10]):
                if not isinstance(d, dict) or not d.get("ticker"):
                    continue
                results.append(ScannerResult(
                    ticker=d["ticker"],
                    rvol=float(d.get("rvol_capped") or d.get("rvol") or 0),
                    price=float(d.get("price", 0)),
                    atr=float(d.get("atr_usd") or d.get("atr") or 0),
                    change_pct=float(d.get("gap_pct") or d.get("change_pct") or 0),
                    rank=i + 1,
                ))

        # ── Fallback: scanner_state.json (watchlist is a list of plain strings) ──
        if not results and state_path.exists():
            s = json.loads(state_path.read_text())
            watchlist = s.get("watchlist", [])
            scores    = s.get("scores", {})
            for i, ticker in enumerate(watchlist[:10]):
                if not isinstance(ticker, str):
                    continue
                results.append(ScannerResult(
                    ticker=ticker,
                    rvol=float(scores.get(ticker, 0)),
                    price=0.0,
                    atr=0.0,
                    change_pct=0.0,
                    rank=i + 1,
                ))

        # ── Live-price refresh: if scan is stale or prices are 0, hit Alpaca ──
        # This keeps the scanner useful throughout the trading day even when the
        # premarket scan file is from a prior session (happens after restarts or
        # when yfinance wasn't installed during the original scan run).
        scan_date = u.get("date", "") if universe_path.exists() else ""
        prices_missing = any(r.price == 0.0 for r in results)
        if results and (scan_date != today_str or prices_missing):
            live = _fetch_live_prices([r.ticker for r in results])
            for r in results:
                if live.get(r.ticker, 0) > 0:
                    r.price = live[r.ticker]

        return results
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/scan-now")
def trigger_scan_now() -> dict:
    """
    Manually trigger a fresh premarket scan outside the normal 9:00–11:30 ET
    window.  Useful after a restart when daily_universe.json is stale.

    Runs synchronously in the API worker — takes ~5–15 seconds.
    Returns {"ok": true, "universe": [...], "count": n} on success.
    """
    try:
        from broker import get_clients
        from scanner import daily_premarket_scan
        alpaca, _ = get_clients()
        universe = daily_premarket_scan(alpaca, force=True)
        return {"ok": True, "universe": universe, "count": len(universe)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/opening-range/{ticker}")
def get_opening_range(ticker: str) -> dict:
    """
    Return the Opening Range (9:30–9:40 ET) for today's session.

    Uses 5-minute bars (same source as the chart) so the result stays
    consistent with what the chart is drawing.  Falls back to Alpaca 1Min
    with limit=390 (full 6.5-hour session) if needed, so the 9:30 bars are
    always included regardless of what time of day the request arrives.

    The old approach of limit=50 1Min bars broke after 10:20 AM because the
    50 most recent bars no longer contained the 9:30–9:40 opening window.
    """
    try:
        import datetime as _dt
        import pandas as pd
        from signals import bars_to_df, get_opening_range as _get_or

        # ── Attempt 1: yfinance 5-minute bars (same as the chart) ────────────
        # Use prepost=True (same as main chart) — prepost=False can return
        # timezone-naive timestamps that the utc=True conversion misinterprets,
        # causing the 9:30 UTC bar (= 5:30 AM ET premarket) to match the
        # get_opening_range filter instead of the real 9:30 AM ET bar.
        # We filter to regular session hours explicitly after conversion.
        try:
            import yfinance as yf
            _today      = _dt.date.today()
            _start_date = _today.strftime("%Y-%m-%d")
            _end_date   = (_today + _dt.timedelta(days=1)).strftime("%Y-%m-%d")
            raw_yf = yf.download(
                ticker,
                start=_start_date,
                end=_end_date,
                interval="5m",
                prepost=True,   # same as main chart — we filter to session below
                progress=False,
                auto_adjust=True,
            )
            if not raw_yf.empty:
                if hasattr(raw_yf.columns, "get_level_values"):
                    raw_yf.columns = raw_yf.columns.get_level_values(0)
                raw_yf = raw_yf.rename(columns={
                    "Open": "open", "High": "high",
                    "Low": "low",  "Close": "close", "Volume": "volume",
                })
                raw_yf.index.name = "time"
                raw_yf = raw_yf.reset_index()
                raw_yf["time"] = (
                    pd.to_datetime(raw_yf["time"], utc=True)
                    .dt.tz_convert("America/New_York")
                    .dt.tz_localize(None)
                )
                df = raw_yf[["time", "open", "high", "low", "close", "volume"]].copy()
                # Explicit regular-session filter: 9:30 AM – 4:00 PM ET.
                # This is the fix: excludes premarket bars regardless of
                # what yfinance returns with the prepost setting.
                session_mask = (
                    (df["time"].dt.hour > 9) |
                    ((df["time"].dt.hour == 9) & (df["time"].dt.minute >= 30))
                ) & (df["time"].dt.hour < 16)
                df = df[session_mask].copy()
                result = _get_or(df)
                if result:
                    return result
        except Exception:
            pass

        # ── Attempt 2: Alpaca 1Min with full-session limit so 9:30 is included ─
        from broker import get_clients
        alpaca, _ = get_clients()
        raw = alpaca.get_bars(ticker, "1Min", limit=390)  # 390 = full 6.5h session
        bars = raw[0] if isinstance(raw, tuple) else raw
        if not bars:
            return {}
        df = bars_to_df(bars)
        return _get_or(df) or {}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
