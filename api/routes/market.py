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
    from signals import bars_to_df, compute_vwap, compute_rvol, compute_atr

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
                df = raw_yf[["time","open","high","low","close","volume"]].tail(limit).reset_index(drop=True)
        except Exception:
            pass

    if df.empty:
        raise HTTPException(status_code=503, detail=f"No bar data available for {ticker} from Alpaca or yfinance")

    df["vwap"] = compute_vwap(df)
    df["rvol"] = compute_rvol(df)
    df["atr"]  = compute_atr(df)

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
            vwap=float(row["vwap"]) if pd.notna(row.get("vwap")) else None,
            rvol=float(row["rvol"]) if pd.notna(row.get("rvol")) else None,
            atr=float(row["atr"])  if pd.notna(row.get("atr"))  else None,
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
    try:
        import json
        from pathlib import Path
        state_path = Path(__file__).resolve().parents[2] / "scanner_state.json"
        if not state_path.exists():
            return []
        data = json.loads(state_path.read_text())
        results = []
        for i, item in enumerate(data.get("watchlist", [])[:10]):
            results.append(ScannerResult(
                ticker=item.get("ticker", ""),
                rvol=float(item.get("rvol", 0)),
                price=float(item.get("price", 0)),
                atr=float(item.get("atr", 0)),
                change_pct=float(item.get("change_pct", 0)),
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
