"""
api/routes/market.py — Market data: bars, quotes, scanner results.
"""
from __future__ import annotations
from fastapi import APIRouter, HTTPException, Query
from api.models import Bar, Quote, ScannerResult

router = APIRouter(prefix="/api/market", tags=["market"])


@router.get("/bars/{ticker}", response_model=list[Bar])
def get_bars(
    ticker: str,
    timeframe: str = Query("5Min", enum=["1Min", "5Min", "15Min", "1Hour"]),
    limit: int = Query(200, ge=10, le=1000),
) -> list[Bar]:
    """
    Fetch OHLCV bars with pre/after-market data.
    Attempt 1: Alpaca IEX (session=extended).
    Attempt 2: yfinance with prepost=True — already installed, used by the
               trading engine for the SPY VWAP gate. Covers 4 AM–8 PM ET.
    """
    import pandas as pd
    from signals import bars_to_df, compute_vwap, compute_vwap_bands, compute_rvol, compute_atr

    df = pd.DataFrame()

    # ── Attempt 1: Alpaca ─────────────────────────────────────────────────────
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
            # Map our timeframe strings to yfinance intervals
            _yf_interval = {"1Min": "1m", "5Min": "5m", "15Min": "15m", "1Hour": "60m"}.get(timeframe, "5m")
            # yfinance 1m limited to 7 days; 5m/15m up to 60 days
            _period = "7d" if _yf_interval == "1m" else "60d"
            raw_yf = yf.download(
                ticker,
                period=_period,
                interval=_yf_interval,
                prepost=True,       # include pre-market 4 AM and after-hours to 8 PM
                progress=False,
                auto_adjust=True,
            )
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


@router.get("/scanner", response_model=list[ScannerResult])
def get_scanner() -> list[ScannerResult]:
    """
    Returns today's premarket scan results.

    Reads from daily_universe.json (scan_details) which stores full per-ticker
    metrics (rvol, price, atr, gap_pct, score).  Falls back to scanner_state.json
    if daily_universe.json is missing or stale.  scanner_state.json watchlist is a
    plain list of strings — never call .get() on the items directly.
    """
    try:
        import json
        from pathlib import Path

        base = Path(__file__).resolve().parents[2]
        universe_path = base / "daily_universe.json"
        state_path    = base / "scanner_state.json"
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
            if results:
                return results

        # ── Fallback: scanner_state.json (watchlist is a list of plain strings) ──
        if state_path.exists():
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
        return results
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/opening-range/{ticker}")
def get_opening_range(ticker: str) -> dict:
    try:
        from broker import get_clients
        from signals import bars_to_df, get_opening_range as _get_or
        alpaca, _ = get_clients()
        raw = alpaca.get_bars(ticker, "1Min", limit=50)
        bars = raw[0] if isinstance(raw, tuple) else raw
        if not bars:
            return {}
        df = bars_to_df(bars)
        return _get_or(df) or {}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
