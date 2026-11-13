"""
api/routes/market.py — Market data: bars, quotes, scanner results.
"""
from __future__ import annotations
from datetime import datetime
import json
import pytz
from pathlib import Path
from fastapi import APIRouter, HTTPException, Query
from api.models import Bar, Quote, ScannerResult, OptionsChainRow
from trading.state import _now_et

# Shared path used by scanner and premarket endpoints
universe_path = Path(__file__).resolve().parents[2] / "daily_universe.json"

router = APIRouter(prefix="/api/market", tags=["market"])

_ET = pytz.timezone("America/New_York")


def _rank_premarket_results(results: list[dict]) -> list[dict]:
    """Return complete morning reports from strongest match score to weakest."""
    ranked = sorted(
        results,
        key=lambda row: (
            int(row.get("fit_score") or 0),
            bool(row.get("tradeable_today")),
            bool(row.get("is_pinned")),
        ),
        reverse=True,
    )
    for rank, row in enumerate(ranked, 1):
        row["rank"] = rank
    return ranked


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
    limit: int = Query(200, ge=10, le=2000),
    premarket: bool = False,
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

    # ── yfinance: 30-day history (always used for the chart) ─────────────────
    # Alpaca's get_session_bars returns only TODAY's session, which leaves the
    # chart with 4-5 bars early in the morning and breaks period view + RSI/MACD.
    # yfinance with a 30-day lookback gives the full history the chart needs.
    if True:
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
            _today      = _now_et().date()
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
                # Display-only session selection. Trading data and rules are unchanged.
                import datetime as _dt2
                _open = _dt2.time(4, 0) if premarket else _dt2.time(9, 30)
                _close = _dt2.time(16, 0)
                # Use explicit >= / < instead of .between() so that 4:00 PM bars
                # (first extended-hours bar) are excluded (.between is inclusive on both ends)
                _t = raw_yf["time"].dt.time
                raw_yf = raw_yf[(_t >= _open) & (_t < _close)].reset_index(drop=True)
                if raw_yf.empty:
                    df = pd.DataFrame()
                else:
                    df = raw_yf.tail(limit).reset_index(drop=True)
        except Exception:
            pass

    if df.empty:
        raise HTTPException(status_code=503, detail=f"No bar data available for {ticker} from yfinance")

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
        import datetime as _dt

        state_path = Path(__file__).resolve().parents[2] / "scanner_state.json"
        today_str  = _now_et().date().isoformat()
        results: list[ScannerResult] = []
        u: dict = {}

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
        scan_date = u.get("date", "") if universe_path.exists() else ""
        prices_missing = any(r.price == 0.0 for r in results)
        if results and (scan_date != today_str or prices_missing):
            live = _fetch_live_prices([r.ticker for r in results])
            for r in results:
                if live.get(r.ticker, 0) > 0:
                    r.price = live[r.ticker]

        # ── Always include all user watchlist tickers with live data ──────────
        # scan_details only contains tickers that passed gap+RVOL filters.
        # Watchlist-pinned tickers that didn't gap enough get silently dropped —
        # this patch adds them back with their real snapshot prices/change_pct.
        try:
            from config import get_settings as _gs
            _wl      = [t.upper().strip() for t in (_gs().get("watchlist") or []) if t.strip()]
            _have    = {r.ticker for r in results}
            _missing = [t for t in _wl if t not in _have]
            if _missing:
                from broker import get_clients as _gc
                _alp, _ = _gc()
                _snaps   = _alp.get_snapshots(_missing) or {}
                for _t in _missing:
                    _s = _snaps.get(_t, {})
                    results.append(ScannerResult(
                        ticker=_t,
                        rvol=0.0,
                        price=float(_s.get("price", 0) or 0),
                        atr=0.0,
                        change_pct=float(_s.get("change_pct", 0) or 0),
                        rank=len(results) + 1,
                    ))
        except Exception:
            pass

        return results
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/chain/{ticker}", response_model=list[OptionsChainRow])
def get_options_chain(ticker: str) -> list[OptionsChainRow]:
    """
    Return the near-term options chain for a ticker, combining calls and puts
    into a single per-strike table.  Uses Tradier's live chain endpoint.
    Only returns the nearest 7–21 DTE expiry (same window the bot trades).

    Result is a list of OptionsChainRow sorted by strike ascending.  Strikes
    that have only calls or only puts still appear — the other side is null.
    """
    try:
        from broker import get_clients
        _, tradier = get_clients()

        # Get the nearest expiry in our trading window (7–21 DTE)
        expirations = tradier.get_expirations(ticker)
        if not expirations:
            return []

        expiry = expirations[0]

        # Fetch both sides.  The broker method filters by spread / OI so we see
        # only the liquid strikes — fine for a trading dashboard.
        calls = tradier.get_option_chain(ticker, expiry, option_type="call")
        puts  = tradier.get_option_chain(ticker, expiry, option_type="put")

        # Build strike → {call, put} merged dict
        strikes: dict[float, dict] = {}
        for c in calls:
            s = float(c.get("strike", 0))
            if s:
                strikes.setdefault(s, {})["call"] = c
        for p in puts:
            s = float(p.get("strike", 0))
            if s:
                strikes.setdefault(s, {})["put"] = p

        result = []
        for strike in sorted(strikes.keys()):
            row  = strikes[strike]
            call = row.get("call", {})
            put  = row.get("put",  {})
            result.append(OptionsChainRow(
                strike     = strike,
                call_bid   = call.get("bid"),
                call_ask   = call.get("ask"),
                call_mid   = call.get("mid"),
                call_delta = call.get("delta"),
                call_iv    = call.get("iv"),
                call_oi    = call.get("open_interest"),
                put_bid    = put.get("bid"),
                put_ask    = put.get("ask"),
                put_mid    = put.get("mid"),
                put_delta  = put.get("delta"),
                put_iv     = put.get("iv"),
                put_oi     = put.get("open_interest"),
            ))
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/premarket")
def get_premarket_report(tickers: str = Query("")) -> list[dict]:
    from api.daily_brief import read_report
    rows = read_report()
    if tickers:
        selected = {ticker.strip().upper() for ticker in tickers.split(',')}
        rows = [row for row in rows if row['ticker'] in selected]
    return rows


def build_premarket_report(tickers: str = "") -> list[dict]:
    """
    Rich premarket analysis for the user's watchlist + scanner-found tickers.

    Returns per-ticker:
      price, prev_close, prev_high, prev_low, gap_pct,
      atr, atr_pct, avg_vol_20d, daily_vol, rvol,
      implied_move_pct, readiness score (not a probability),
      multi-timeframe market bias, strategy matches, key_levels,
      entry_note, stop_note, target_note, setup_notes,
      is_pinned, rank

    Data sources:
      - yfinance daily/intraday bars (batch) → five-timeframe context
      - Alpaca snapshots                    → live price and today's volume
    """
    import concurrent.futures
    import datetime as _dt
    import pandas as pd
    from config import get_settings as _gs

    # ── Build unified ticker list ─────────────────────────────────────────────
    _settings    = _gs()
    _pins        = [t.upper().strip() for t in (_settings.get("watchlist") or []) if t.strip()]
    _extra       = [t.upper().strip() for t in tickers.split(",") if t.strip()] if tickers else []
    from api.daily_brief import trading_tickers
    allowed = trading_tickers(_settings)
    all_tickers = [ticker for ticker in dict.fromkeys(_pins + _extra + allowed)
                   if ticker in allowed]
    if not all_tickers:
        return []

    def _symbol_frame(raw, symbol: str):
        """Normalize either yfinance MultiIndex orientation for one symbol."""
        if raw is None or raw.empty or not isinstance(raw.columns, pd.MultiIndex):
            return raw
        for level in range(raw.columns.nlevels):
            values = {str(value).upper() for value in raw.columns.get_level_values(level)}
            if symbol.upper() in values:
                return raw.xs(symbol, level=level, axis=1, drop_level=True)
        return raw

    # ── Batch daily bars via yfinance (22 days → ATR + prev H/L/C + avg vol) ─
    yf_bars: dict[str, list] = {}
    try:
        import yfinance as _yf
        _today = _now_et().date()
        _start = (_today - _dt.timedelta(days=35)).strftime("%Y-%m-%d")
        _end   = (_today + _dt.timedelta(days=1)).strftime("%Y-%m-%d")

        def _dl():
            return _yf.download(all_tickers, start=_start, end=_end,
                                interval="1d", progress=False, auto_adjust=True,
                                group_by="ticker")

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as _ex:
            _raw = _ex.submit(_dl).result(timeout=20)

        def _daily_records(frame):
            frame = frame.dropna(subset=["Close"])
            if frame.empty:
                return []
            rows = frame[["Open", "High", "Low", "Close", "Volume"]].tail(24).rename(
                columns={"Open":"o", "High":"h", "Low":"l", "Close":"c", "Volume":"v"}
            )
            records = rows.to_dict("records")
            for record, stamp in zip(records, rows.index):
                record["session"] = str(getattr(stamp, "date", lambda: stamp)())
                record["is_complete"] = record["session"] != _now_et().date().isoformat()
            return records

        if not _raw.empty:
            for _t in all_tickers:
                try:
                    _records = _daily_records(_symbol_frame(_raw, _t))
                    if _records:
                        yf_bars[_t] = _records
                except Exception:
                    pass
    except Exception:
        pass  # proceed with Alpaca-only data

    # Extended-hours intraday context. These are real completed Yahoo bars;
    # the pure evaluator below never projects a future candle. Batch requests
    # keep this to two calls for the whole report instead of two per ticker.
    intraday_1m: dict[str, list] = {}
    hourly_1h: dict[str, list] = {}
    try:
        import yfinance as _yf_intraday

        def _intraday_download(interval: str, days: int):
            _today_i = _now_et().date()
            return _yf_intraday.download(
                all_tickers,
                start=(_today_i - _dt.timedelta(days=days)).strftime("%Y-%m-%d"),
                end=(_today_i + _dt.timedelta(days=1)).strftime("%Y-%m-%d"),
                interval=interval, prepost=True, progress=False, auto_adjust=True,
                group_by="ticker",
            )

        def _split_intraday(raw, target: dict[str, list], tail: int) -> None:
            if raw is None or raw.empty:
                return
            for symbol in all_tickers:
                try:
                    frame = _symbol_frame(raw, symbol)
                    frame = frame.dropna(subset=["Close"])
                    if frame.empty:
                        continue
                    target[symbol] = frame[["Open", "High", "Low", "Close", "Volume"]].tail(tail).rename(
                        columns={"Open":"o", "High":"h", "Low":"l", "Close":"c", "Volume":"v"}
                    ).to_dict("records")
                except Exception:
                    continue

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as _ex:
            one_minute_future = _ex.submit(_intraday_download, "1m", 5)
            hourly_future = _ex.submit(_intraday_download, "60m", 60)
            _split_intraday(one_minute_future.result(timeout=20), intraday_1m, 1800)
            _split_intraday(hourly_future.result(timeout=20), hourly_1h, 300)
    except Exception:
        pass

    # ── Alpaca snapshots: live price, change_pct, today's volume ─────────────
    try:
        from broker import get_clients as _gc
        _alp, _ = _gc()
        _snaps = _alp.get_snapshots(all_tickers) or {}
    except Exception:
        _snaps = {}

    # ── Helpers ───────────────────────────────────────────────────────────────
    _pin_set = set(_pins)

    def _calc_atr(bars: list) -> float:
        if len(bars) < 2:
            return 0.0
        bars = [bar for bar in bars if bar.get("is_complete") is not False][-15:]
        trs = []
        for i in range(1, len(bars)):
            h = float(bars[i].get("h", 0) or 0)
            l = float(bars[i].get("l", 0) or 0)
            pc = float(bars[i-1].get("c", 0) or 0)
            trs.append(max(h - l, abs(h - pc), abs(l - pc)))
        return round(sum(trs[-14:]) / min(len(trs), 14), 2) if trs else 0.0

    # ── Per-ticker processing ─────────────────────────────────────────────────
    results = []
    for rank, ticker in enumerate(all_tickers, 1):
        try:
            snap  = _snaps.get(ticker, {})
            bars  = yf_bars.get(ticker, [])
            price       = float(snap.get("price",      0) or 0)
            change_pct  = float(snap.get("change_pct", 0) or 0)
            daily_vol   = float(snap.get("daily_vol",  0) or 0)
            prev_close_snap = float(snap.get("prev_close", 0) or 0)
            if price <= 0 and intraday_1m.get(ticker):
                price = float(intraday_1m[ticker][-1].get("c", 0) or 0)
            if price <= 0 and bars:
                price = float(bars[-1].get("c", 0) or 0)
            if daily_vol <= 0 and intraday_1m.get(ticker):
                daily_vol = sum(float(row.get("v", 0) or 0) for row in intraday_1m[ticker][-960:])

            # Previous day's OHLCV from yfinance bars[-2] (bars[-1] may be partial today)
            prev_high = prev_low = prev_close = avg_vol_20d = 0.0
            atr_val   = 0.0
            _complete_bars = [bar for bar in bars if bar.get("is_complete") is not False]
            if _complete_bars:
                _pb       = _complete_bars[-1]
                prev_high = float(_pb.get("h", 0) or 0)
                prev_low  = float(_pb.get("l", 0) or 0)
                prev_close = float(_pb.get("c", 0) or 0)
                _vols     = [float(b.get("v", 0) or 0) for b in _complete_bars]
                avg_vol_20d = sum(_vols[-20:]) / max(len(_vols[-20:]), 1)
                atr_val   = _calc_atr(bars)

            # Prefer Alpaca prev_close if yfinance didn't return enough bars
            if prev_close <= 0:
                prev_close = prev_close_snap

            gap_pct = (price - prev_close) / prev_close * 100 if (price > 0 and prev_close > 0) else change_pct

            # Time-normalized RVOL
            rvol = 0.0
            if avg_vol_20d > 0 and daily_vol > 0:
                _clock_et = _now_et()
                _open_et  = _clock_et.replace(hour=9, minute=30, second=0, microsecond=0)
                _elapsed  = max(1.0, (_clock_et - _open_et).total_seconds() / 60.0)
                _expected = max(avg_vol_20d * min(_elapsed / 390.0, 1.0), avg_vol_20d / 78.0)
                rvol      = round(daily_vol / _expected, 1)

            from config.strategy_catalog import (
                REVIEWED_STRATEGIES, enabled_reviewed_strategy_ids,
            )
            from scanner.strategy_premarket import (
                multi_timeframe_context, strategy_aware_plan,
            )
            timeframes = multi_timeframe_context(
                minute_bars=intraday_1m.get(ticker, []),
                hourly_bars=hourly_1h.get(ticker, []),
                daily_bars=bars, current_price=price,
            )
            executable_ids = enabled_reviewed_strategy_ids(_settings, ticker=ticker)
            plan = strategy_aware_plan(
                ticker=ticker, context=timeframes, daily_bars=bars,
                gap_pct=gap_pct, rvol=rvol,
                executable_strategy_ids=executable_ids,
                research_strategy_ids=set(REVIEWED_STRATEGIES) - executable_ids,
                hourly_bars=hourly_1h.get(ticker, []),
            )
            fit_score = int(plan["fit_score"])
            grade = "A" if fit_score >= 80 else "B" if fit_score >= 65 else "C" if fit_score >= 50 else "Watch"
            direction = "calls" if plan["direction"] == "bullish" else "puts" if plan["direction"] == "bearish" else "neutral"

            # Key levels (sorted ascending)
            key_levels = []
            def _kl(label, px, typ):
                if px > 0:
                    key_levels.append({"label": label, "price": round(px, 2), "type": typ})
            if atr_val > 0 and price > 0:
                _kl("-1× ATR", price - atr_val, "stop")
            _kl("Prev Day Low",   prev_low,   "support")
            _kl("Prev Close",     prev_close, "reference")
            _kl("Current Price",  price,      "current")
            _kl("Prev Day High",  prev_high,  "resistance")
            if atr_val > 0 and price > 0:
                _kl("+1× ATR", price + atr_val, "target")
            key_levels.sort(key=lambda x: x["price"])

            entry_note = str(plan["entry_note"])
            stop_note = str(plan["stop_note"])
            target_note = str(plan["target_note"])
            setup_notes = str(plan["setup_notes"])

            # A pre-market card is useful only when it has real price and
            # prior-session levels. Incomplete scanner names stay out of the
            # brief instead of promising a report that may arrive too late.
            if price <= 0 or prev_close <= 0 or prev_high <= 0 or prev_low <= 0:
                continue

            results.append({
                "ticker": ticker, "price": round(price, 2),
                "prev_close": round(prev_close, 2), "prev_high": round(prev_high, 2),
                "prev_low": round(prev_low, 2), "gap_pct": round(gap_pct, 2),
                "atr": round(atr_val, 2), "atr_pct": round(atr_val / price * 100, 2) if price > 0 else 0.0,
                "avg_vol_20d": int(avg_vol_20d), "daily_vol": int(daily_vol),
                "rvol": rvol, "implied_move_pct": round(atr_val / price * 100, 2) if price > 0 else 0.0,
                "grade": grade, "direction": direction,
                "fit_score": fit_score,
                "readiness_score": fit_score,
                "tradeable_today": bool(plan["tradeable_today"]),
                "best_strategy": plan["best_strategy"],
                "strategy_matches": plan["strategy_matches"],
                "timeframes": timeframes,
                "entry_note": entry_note, "stop_note": stop_note, "target_note": target_note,
                "key_levels": key_levels, "setup_notes": setup_notes,
                "is_pinned": ticker in _pin_set, "rank": rank,
            })
        except Exception:
            continue

    return _rank_premarket_results(results)


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

    FIX 2026-07-31: this used to try yfinance FIRST and only fall back to
    Alpaca if that failed — reasoned as "same source as the chart" (the main
    candlestick chart's /bars endpoint does prefer yfinance, for its 30-day
    history). But the OR line isn't decorative — it's the exact reference
    level strategies/inst_orb.py trades against, and inst_orb.py's own
    get_opening_range() call is fed Alpaca bars from the live trading loop,
    never yfinance. Real incident: AMD's chart showed OR Hi $515.62 / OR Lo
    $499.39 (yfinance) while the bot was actually detecting breakouts and
    entering retest logic against a ~$504.6-504.8 boundary (Alpaca) — a
    trader watching the chart had no way to see where the bot's own OR
    boundary actually was. Alpaca now tried first so the line drawn always
    matches what the bot is trading against; yfinance is still the fallback
    for when Alpaca's free tier has nothing (market closed, etc.).
    """
    try:
        import pandas as pd
        from signals import bars_to_df, get_opening_range as _get_or

        # ── Attempt 1: Alpaca 1Min, full-session limit so 9:30 is included —
        # the SAME feed inst_orb.py's live evaluate() call is fed, so this
        # line always matches the boundary the bot is actually trading against.
        try:
            from broker import get_clients
            alpaca, _ = get_clients()
            raw = alpaca.get_bars(ticker, "1Min", limit=390)  # 390 = full 6.5h session
            bars = raw[0] if isinstance(raw, tuple) else raw
            if bars:
                df = bars_to_df(bars)
                result = _get_or(df)
                if result:
                    return result
        except Exception:
            pass

        # ── Attempt 2: yfinance 5-minute bars — fallback only, e.g. market
        # closed or Alpaca's free IEX tier has nothing for this ticker yet.
        # Use prepost=True (same as main chart) — prepost=False can return
        # timezone-naive timestamps that the utc=True conversion misinterprets,
        # causing the 9:30 UTC bar (= 5:30 AM ET premarket) to match the
        # get_opening_range filter instead of the real 9:30 AM ET bar.
        # We filter to regular session hours explicitly after conversion.
        try:
            import datetime as _dt
            import yfinance as yf
            _today      = _now_et().date()
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
                session_mask = (
                    (df["time"].dt.hour > 9) |
                    ((df["time"].dt.hour == 9) & (df["time"].dt.minute >= 30))
                ) & (df["time"].dt.hour < 16)
                df = df[session_mask].copy()
                return _get_or(df) or {}
        except Exception:
            pass

        return {}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/news", response_model=list)
def get_news(
    symbols: str = Query("SPY,QQQ"),
    limit: int = Query(10, ge=1, le=50),
) -> list:
    """
    Fetch recent news for one or more tickers via Alpaca's free news API.
    symbols: comma-separated, e.g. "SPY,QQQ,AAPL"
    Falls back to [] with no error if keys are missing or API is unavailable.
    """
    try:
        import requests as _req
        from config import ALPACA_API_KEY, ALPACA_SECRET_KEY, get_api_keys
        _keys      = get_api_keys()
        _api_key   = _keys.get("alpaca_api_key",    ALPACA_API_KEY)
        _secret    = _keys.get("alpaca_secret_key", ALPACA_SECRET_KEY)
        if not _api_key or not _secret:
            return []
        headers = {
            "APCA-API-KEY-ID":     _api_key,
            "APCA-API-SECRET-KEY": _secret,
        }
        params = {
            "symbols": symbols.upper(),
            "limit":   min(limit, 50),
            "sort":    "desc",
        }
        r = _req.get(
            "https://data.alpaca.markets/v1beta1/news",
            headers=headers, params=params, timeout=8,
        )
        r.raise_for_status()
        articles = r.json().get("news", [])
        result = []
        for a in articles:
            result.append({
                "id":         a.get("id"),
                "headline":   a.get("headline", ""),
                "summary":    a.get("summary", ""),
                "source":     a.get("source", ""),
                "url":        a.get("url", ""),
                "created_at": a.get("created_at", ""),
                "symbols":    a.get("symbols", []),
            })
        return result
    except Exception:
        return []   # never fail the frontend; news is supplemental
