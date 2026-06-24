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
    try:
        from broker import get_clients
        from signals import bars_to_df, compute_vwap, compute_rvol, compute_atr
        alpaca, _ = get_clients()
        raw = alpaca.get_bars(ticker, timeframe, limit=limit)
        bars = raw[0] if isinstance(raw, tuple) else raw
        if not bars:
            return []
        df = bars_to_df(bars)
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
                vwap=float(row["vwap"]) if row.get("vwap") is not None else None,
                rvol=float(row["rvol"]) if row.get("rvol") is not None else None,
                atr=float(row["atr"]) if row.get("atr") is not None else None,
            ))
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


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
            price = float(snap.get("latestTrade", {}).get("p", 0) or 0)
            prev  = float(snap.get("prevDailyBar", {}).get("c", price) or price)
            change_pct = ((price - prev) / prev * 100) if prev else 0.0
            vol = float(snap.get("dailyBar", {}).get("v", 0) or 0)
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
