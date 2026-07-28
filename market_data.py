"""
market_data.py — shared market-data fetch helpers used by more than one
module (scanner.py today; anything else that needs real daily volume later).

WHY THIS FILE EXISTS (2026-07-28):
Alpaca's free-tier daily bars are IEX-only — broker.py's get_bars() hardcodes
feed="iex" for every request, daily bars included (not just intraday). IEX is
one exchange among many; its reported volume for a stock is a small slice of
that stock's TRUE (consolidated, all-exchange) volume. Confirmed live: QQQ's
IEX daily volume read 897K and MSFT read 1.2M — both are 20-40M+ share ADV
names in reality.

That's harmless for a RATIO check (today's volume vs this same ticker's own
recent average — both sides are undercounted the same way, so the ratio
survives). It is NOT harmless for an ABSOLUTE liquidity floor, like
scanner.py's "average 20-day volume must be >= 2,000,000 real shares" filter
— comparing an IEX fraction against a threshold meant for real volume
silently rejects almost every liquid ticker in the pool. That's exactly what
was happening: 60 of 62 gap-filtered candidates (including MSFT, QQQ, AVGO)
were being wrongly cut here, leaving an empty scan universe most days.

get_consolidated_daily_bars() fixes the DATA SOURCE, not the threshold — it
fetches real consolidated daily volume from yfinance (free, no API key,
already a dependency elsewhere in this project) as the primary source, and
only falls back to Alpaca's IEX feed per-ticker if yfinance has no data for
that symbol (e.g. a very new listing). Any code that needs a real absolute
volume number should call this instead of alpaca.get_bars(ticker, "1Day").
Code that only needs a same-ticker RATIO (like signals.py's compute_rvol)
does not need this — the IEX-vs-real gap cancels out in a ratio and pulling
yfinance for every live tick would be far too slow for that use case.
"""

from __future__ import annotations

import datetime as _dt
import logging

logger = logging.getLogger("celo_trader.market_data")


def get_consolidated_daily_bars(
    tickers: list[str], alpaca=None, lookback_days: int = 22,
) -> dict[str, list[dict]]:
    """
    Batch-fetch real (consolidated) daily OHLCV bars for a list of tickers.

    Returns {ticker: [{"o","h","l","c","v"}, ...]}, oldest bar first, one
    entry per ticker that returned usable data. Tickers with no data from
    either source are simply absent from the result — callers should treat
    a missing key the same way they'd treat "insufficient bars" today.

    Parameters
    ----------
    tickers       : symbols to fetch
    alpaca        : optional AlpacaClient — used only as a per-ticker
                     fallback (IEX feed) for symbols yfinance can't find
    lookback_days : how many recent daily bars to keep per ticker
    """
    out: dict[str, list[dict]] = {}
    if not tickers:
        return out

    # ── Primary: yfinance batch download — real consolidated volume ────────
    try:
        import yfinance as yf
        end_d   = _dt.date.today() + _dt.timedelta(days=1)
        # Pad the request window generously for weekends/holidays so a
        # lookback_days=22 request still gets ~22 real trading days back.
        start_d = end_d - _dt.timedelta(days=lookback_days * 2 + 10)
        batch = yf.download(
            tickers,
            start=start_d.strftime("%Y-%m-%d"),
            end=end_d.strftime("%Y-%m-%d"),
            interval="1d",
            progress=False,
            auto_adjust=True,
            group_by="ticker",
        )
        for t in tickers:
            try:
                # Multi-ticker download returns a MultiIndex DataFrame;
                # single-ticker returns a plain DataFrame.
                df = batch if len(tickers) == 1 else batch[t]
                if df is None or df.empty:
                    continue
                if hasattr(df.columns, "get_level_values"):
                    df.columns = df.columns.get_level_values(0)
                bars = [
                    {
                        "o": float(r.get("Open",   0) or 0),
                        "h": float(r.get("High",   0) or 0),
                        "l": float(r.get("Low",    0) or 0),
                        "c": float(r.get("Close",  0) or 0),
                        "v": float(r.get("Volume", 0) or 0),
                    }
                    for _, r in df.iterrows()
                    if float(r.get("Close", 0) or 0) > 0
                ]
                if bars:
                    out[t] = bars[-lookback_days:]
            except Exception:
                pass
        logger.info(
            "get_consolidated_daily_bars: yfinance loaded %d/%d tickers",
            len(out), len(tickers),
        )
    except Exception as ex:
        logger.warning("get_consolidated_daily_bars: yfinance batch failed: %s", ex)

    # ── Fallback: Alpaca (IEX) per-ticker, only for symbols yfinance missed ─
    # Volume numbers from this path will read low for the reason explained
    # above — better than nothing (ATR/price data is still IEX-accurate),
    # but any avg-volume comparison against an absolute floor will still be
    # unreliable for these specific tickers.
    if alpaca is not None:
        missing = [t for t in tickers if t not in out]
        for t in missing:
            try:
                bars, err = alpaca.get_bars(t, "1Day", limit=lookback_days)
                if not err and len(bars) >= 10:
                    out[t] = bars
                    logger.debug(
                        "get_consolidated_daily_bars: %s — yfinance had no data, "
                        "used Alpaca IEX fallback (volume will read low)", t,
                    )
            except Exception:
                pass

    return out
