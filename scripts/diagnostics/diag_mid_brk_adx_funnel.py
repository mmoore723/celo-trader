"""
diag_mid_brk_adx_funnel.py — Why does the real pipeline produce ~0 MID_BRK
trades when the raw strategy code finds hundreds of structural signals?

Background: diag_mid_brk_session_scan.py found 422 raw mid_brk.evaluate()
signals inside the current 10:30-13:00 window across 10 tickers/~59 days.
ab_test_mid_brk_session_window.py then ran the SAME window through the full
Backtester (which goes through strategy_router.route_signals(), not a bare
evaluate() call) on SPY/QQQ/NVDA and got 0 trades. Something between the raw
signal and the live pipeline is wiping almost everything out.

The prime suspect: MID_BRK is registered in regime_manager.ADX_GATED_STRATEGIES
(ADX_MIN = 25) — route_signals() skips calling mid_brk.evaluate() AT ALL on
any bar where ADX(14) < 25. MID_BRK's whole premise is a breakdown AFTER a
quiet, low-volatility late-morning/midday consolidation — which is exactly
when ADX is often lowest (the "lunch lull"). If that's true, the ADX gate may
structurally exclude MID_BRK from most of its own best setups, unlike pure
trend-following strategies (INST_ORB, TREND_CONT) where requiring an
already-trending tape makes sense.

This script reruns the raw signal scan but ALSO computes the real ADX(14)
value (same function route_signals() calls: regime_manager.compute_adx_series)
at the moment of every signal, so we can see exactly what fraction of raw
MID_BRK signals are being thrown out by the ADX>=25 gate alone, before the
confidence floor or any other gate even gets a chance to run.

Usage:
    python3 diag_mid_brk_adx_funnel.py                     # default ticker list
    python3 diag_mid_brk_adx_funnel.py SPY QQQ NVDA
"""

from __future__ import annotations

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repo root, needed after this script's move into scripts/<subdir>/

import pandas as pd

from broker import AlpacaClient
from signals import bars_to_df, compute_rvol, compute_vwap_bands
import strategies.mid_brk as mid_brk
from regime_manager import compute_adx_series, ADX_MIN

DEFAULT_TICKERS = ["SPY", "QQQ", "NVDA", "AAPL", "TSLA", "AMD", "META", "AMZN", "MSFT", "GOOGL"]
FORWARD_BARS    = 12


def _fetch_bars(alpaca: AlpacaClient, ticker: str) -> pd.DataFrame:
    import datetime as _dt
    df = pd.DataFrame()
    try:
        import yfinance as yf
        _today   = _dt.date.today()
        _start_d = (_today - _dt.timedelta(days=59)).strftime("%Y-%m-%d")
        _end_d   = (_today + _dt.timedelta(days=1)).strftime("%Y-%m-%d")
        raw = yf.download(ticker, start=_start_d, end=_end_d, interval="5m",
                           progress=False, auto_adjust=True)
        if not raw.empty:
            if hasattr(raw.columns, "get_level_values"):
                raw.columns = raw.columns.get_level_values(0)
            raw = raw.rename(columns={"Open": "open", "High": "high", "Low": "low",
                                       "Close": "close", "Volume": "volume"})
            raw.index.name = "time"
            raw = raw.reset_index()
            raw["time"] = (pd.to_datetime(raw["time"], utc=True)
                            .dt.tz_convert("America/New_York").dt.tz_localize(None))
            df = raw[["time", "open", "high", "low", "close", "volume"]].copy()
    except Exception:
        pass

    if df.empty:
        raw2 = alpaca.get_bars(ticker, "5Min", limit=10000)
        bars = raw2[0] if isinstance(raw2, tuple) else raw2
        if bars:
            df = bars_to_df(bars)
    return df


def _build_frame(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["rvol"]      = compute_rvol(df, lookback_days=10)
    df["ema50"]     = df["close"].ewm(span=50, adjust=False).mean()
    df["vol_sma20"] = df["volume"].rolling(100, min_periods=20).mean()
    hl  = df["high"] - df["low"]
    hcp = (df["high"] - df["close"].shift(1)).abs()
    lcp = (df["low"]  - df["close"].shift(1)).abs()
    tr  = pd.concat([hl, hcp, lcp], axis=1).max(axis=1)
    df["atr"] = tr.ewm(span=14, adjust=False).mean()
    vwap_frame = compute_vwap_bands(df, num_stds=(1, 2))
    df["vwap"] = vwap_frame["vwap"].ffill()
    return df


def _scan_ticker(df: pd.DataFrame, ticker: str) -> list[dict]:
    """Real evaluate() at the CURRENT live 10:30-13:00 window, with the real
    ADX(14) looked up at each signal bar — same series route_signals() uses."""
    # Precompute ADX once over the whole multi-day history (cheap, one pass),
    # exactly like regime_manager.compute_adx() is fed the full df in live/backtest.
    adx_series = compute_adx_series(df)  # indexed by 5-min bucket timestamp

    found = []
    df["_date"] = df["time"].dt.date
    for day, day_df in df.groupby("_date"):
        day_df = day_df.reset_index(drop=True)
        if len(day_df) < 15:
            continue
        for i in range(10, len(day_df)):
            slice_df = day_df.iloc[: i + 1].reset_index(drop=True)
            try:
                sig = mid_brk.evaluate(slice_df, ticker=ticker)
            except Exception:
                continue
            if sig is None:
                continue
            bar_time = day_df.iloc[i]["time"]

            adx_val = None
            if adx_series is not None and not adx_series.empty:
                prior = adx_series[adx_series.index <= bar_time]
                if not prior.empty:
                    adx_val = float(prior.iloc[-1])

            passes_adx = (adx_val is None) or (adx_val >= ADX_MIN)  # fail-open, matches route_signals

            fwd_idx = i + FORWARD_BARS
            fwd_pct = None
            if fwd_idx < len(day_df):
                entry_px = float(day_df.iloc[i]["close"])
                fwd_px   = float(day_df.iloc[fwd_idx]["close"])
                fwd_pct  = (fwd_px - entry_px) / entry_px * 100

            found.append({
                "ticker": ticker, "date": str(day), "time": str(bar_time),
                "confidence": sig.confidence, "adx": adx_val,
                "passes_adx_gate": passes_adx,
                "fwd_pct": fwd_pct,
                "worked": (fwd_pct is not None and fwd_pct < -0.10),
            })
    return found


def main() -> None:
    tickers = [t.upper() for t in sys.argv[1:]] or DEFAULT_TICKERS
    alpaca  = AlpacaClient()

    all_signals: list[dict] = []
    for ticker in tickers:
        print(f"⏳ {ticker}…", flush=True)
        df = _fetch_bars(alpaca, ticker)
        if df.empty or len(df) < 100:
            print(f"  (no usable data for {ticker}, skipping)")
            continue
        df = _build_frame(df)
        all_signals.extend(_scan_ticker(df, ticker))

    total = len(all_signals)
    print("\n" + "=" * 92)
    print(f"MID_BRK ADX-GATE FUNNEL — {len(tickers)} ticker(s), current live 10:30-13:00 window")
    print("=" * 92)
    print(f"\nTotal raw evaluate() signals in the live window: {total}")

    if total == 0:
        print("No raw signals found in this sample — nothing to funnel.")
        return

    have_adx   = [s for s in all_signals if s["adx"] is not None]
    no_adx     = total - len(have_adx)
    passed     = [s for s in all_signals if s["passes_adx_gate"]]
    blocked    = [s for s in all_signals if not s["passes_adx_gate"]]
    conf_ok    = [s for s in passed if s["confidence"] >= 0.74]

    print(f"  ADX unavailable (fail-open, gate skipped): {no_adx}")
    print(f"  ADX available:                             {len(have_adx)}")
    if have_adx:
        avg_adx = sum(s["adx"] for s in have_adx) / len(have_adx)
        print(f"  Average ADX at signal time:                {avg_adx:.1f}  (gate requires >= {ADX_MIN:.0f})")

    print(f"\n  Survive ADX >= {ADX_MIN:.0f} gate:              {len(passed)} / {total} "
          f"({len(passed)/total*100:.0f}%)")
    print(f"  Blocked by ADX gate (never reach router):  {len(blocked)} / {total} "
          f"({len(blocked)/total*100:.0f}%)")
    print(f"\n  Of the {len(passed)} that clear ADX, also clear confidence >= 0.74: {len(conf_ok)} "
          f"({(len(conf_ok)/len(passed)*100 if passed else 0):.0f}% of ADX-survivors)")

    def _quality(name: str, rows: list[dict]) -> None:
        rows_with_fwd = [r for r in rows if r["fwd_pct"] is not None]
        n = len(rows_with_fwd)
        if n == 0:
            print(f"  {name:<38} (no forward-return data)")
            return
        wins = sum(1 for r in rows_with_fwd if r["worked"])
        avg  = sum(r["fwd_pct"] for r in rows_with_fwd) / n
        print(f"  {name:<38} n={n:>4}  worked={wins:>3} ({wins/n*100:.0f}%)  avg 60m fwd={avg:+.3f}%")

    print("\nSignal quality — blocked vs surviving:")
    _quality("ADX-BLOCKED signals (never traded live)", blocked)
    _quality("ADX-SURVIVING signals", passed)

    print("\nIf ADX-blocked signals are common (large % blocked) AND their quality is")
    print("comparable to or better than ADX-surviving ones, MID_BRK's ADX>=25 gate is")
    print("likely mismatched to its premise (breakdown AFTER a low-volatility midday")
    print("lull) and worth A/B testing removal — build ab_test_mid_brk_adx_gate.py next.")
    print("If blocked signals are rare or clearly worse quality, the ADX gate is doing")
    print("its job and the near-zero live trade count is a data/sample-size issue, not a bug.")


if __name__ == "__main__":
    main()
