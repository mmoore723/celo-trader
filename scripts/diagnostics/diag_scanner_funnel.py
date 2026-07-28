"""
diag_scanner_funnel.py — 2026-07-28, why is daily_universe.json's
scan_details empty?

WHY THIS EXISTS: the last known daily_universe.json (2026-07-24) has
"scan_details": [] — zero candidates made it all the way through
scanner.py::daily_premarket_scan()'s filter pipeline that day. That write
path itself isn't buggy (traced: details=scored[:max_tickers], and scored
is built by a real 5-stage filter — price, gap%, avg volume, ATR, RVOL).
An empty result could be a real "nothing worth trading today" outcome, OR
one stage could be silently rejecting everything (e.g. if daily_vol/RVOL
data feeding it is bad, same class of issue as the RVOL bug already found
and fixed in signals.py). This script replicates the SAME filter pipeline
with a running tally printed at each stage, using today's real data, so we
can see exactly where candidates are getting cut instead of guessing.

Run on your Mac (real Alpaca network access):
    python3 scripts/diagnostics/diag_scanner_funnel.py
"""

from __future__ import annotations

import sys
import datetime as _dt
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from broker import AlpacaClient
from market_data import get_consolidated_daily_bars
from scanner import (
    LIQUID_POOL, TICKER_BLACKLIST, ANCHOR_TICKERS, _ETF_SET,
    _MIN_PRICE, _MIN_GAP_PCT, _MAX_GAP_PCT, _MIN_GAP_PCT_ETF,
    _MIN_AVG_DAILY_VOL, _MIN_ATR_DOLLARS, _MIN_RVOL, _MIN_RVOL_ETF,
    _compute_atr,
)


def main() -> None:
    alpaca = AlpacaClient()

    now = _dt.datetime.now()
    session_open_min = 9 * 60 + 30
    current_min = now.hour * 60 + now.minute
    elapsed_min = max(1.0, current_min - session_open_min)
    print(f"Local time: {now.strftime('%H:%M')}  (elapsed since 9:30 assumed ET: {elapsed_min:.0f} min — "
          f"adjust manually if your Mac isn't on ET)")

    pool = list(dict.fromkeys([t for t in LIQUID_POOL if t not in TICKER_BLACKLIST]))
    print(f"\nStage 0 — pool size: {len(pool)} tickers")

    all_snaps: dict[str, dict] = {}
    batch_size = 50
    for i in range(0, len(pool), batch_size):
        batch = pool[i:i + batch_size]
        try:
            snaps = alpaca.get_snapshots(batch)
            all_snaps.update(snaps)
        except Exception as ex:
            print(f"  snapshot batch {i // batch_size} failed: {ex}")
    print(f"Stage 1 — got snapshots for: {len(all_snaps)}/{len(pool)} tickers")
    if all_snaps:
        _sample = next(iter(all_snaps.items()))
        print(f"  sample snapshot ({_sample[0]}): {_sample[1]}")

    candidates = []
    n_price_fail = 0
    n_gap_fail = 0
    for ticker, snap in all_snaps.items():
        price = snap.get("price", 0) or 0
        prev_close = snap.get("prev_close", 0) or 0
        open_price = snap.get("open_price", 0) or 0
        daily_vol = snap.get("daily_vol", 0) or 0
        if price < _MIN_PRICE:
            n_price_fail += 1
            continue
        gap_ref = open_price if open_price > 1.0 else price
        if prev_close <= 0:
            n_gap_fail += 1
            continue
        gap_pct = (gap_ref - prev_close) / prev_close * 100
        abs_gap = abs(gap_pct)
        gap_min = _MIN_GAP_PCT_ETF if ticker in _ETF_SET else _MIN_GAP_PCT
        if abs_gap < gap_min or abs_gap > _MAX_GAP_PCT:
            n_gap_fail += 1
            continue
        candidates.append({"ticker": ticker, "price": price, "abs_gap": abs_gap,
                            "gap_pct": gap_pct, "daily_vol": daily_vol, "prev_close": prev_close})
    print(f"Stage 2 — price >= ${_MIN_PRICE}: {n_price_fail} rejected")
    print(f"Stage 3 — gap% in [{_MIN_GAP_PCT_ETF}-{_MAX_GAP_PCT}]% (ETF) / "
          f"[{_MIN_GAP_PCT}-{_MAX_GAP_PCT}]% (stock): {n_gap_fail} rejected")
    print(f"  -> {len(candidates)} candidates survive price+gap filter")
    if candidates:
        print(f"  survivors: {[c['ticker'] for c in candidates][:15]}")

    # FIX 2026-07-28: scanner.py now sources daily bars from
    # get_consolidated_daily_bars() (market_data.py) — real consolidated
    # volume via yfinance first, Alpaca IEX only as a per-ticker fallback.
    # Mirror that here so this diagnostic matches production exactly.
    _daily_bars_cache = get_consolidated_daily_bars(
        [c["ticker"] for c in candidates], alpaca=alpaca, lookback_days=22,
    )
    print(f"\n  daily bars sourced for {len(_daily_bars_cache)}/{len(candidates)} candidates "
          f"(yfinance primary, Alpaca IEX fallback)")

    n_bars_fail = 0
    n_vol_fail = 0
    n_atr_fail = 0
    n_rvol_fail = 0
    scored = []
    for c in candidates:
        ticker = c["ticker"]
        bars = _daily_bars_cache.get(ticker, [])
        if len(bars) < 10:
            n_bars_fail += 1
            continue
        vol_bars = bars[-20:]
        vols = [float(b.get("v", 0)) for b in vol_bars]
        avg_daily_vol = sum(vols) / len(vols) if vols else 0.0
        if avg_daily_vol < _MIN_AVG_DAILY_VOL:
            n_vol_fail += 1
            # PRINT EVERY rejection here, not just a count — broker.py's
            # get_bars() hard-codes feed="iex" for 1Day bars regardless of
            # plan (line ~382), and IEX-only volume is a small slice of a
            # stock's true consolidated volume. If names like MSFT/QQQ/AVGO
            # are getting cut here, that's the smoking gun, not "no volume
            # today" — a name like MSFT trading under 2M shares/day would be
            # front-page news. Printing every ticker's real avg_daily_vol so
            # we can see the actual magnitude gap instead of guessing.
            print(f"    {ticker}: avg_daily_vol={avg_daily_vol:,.0f} "
                  f"(need {_MIN_AVG_DAILY_VOL:,.0f}) -> REJECTED  "
                  f"[bars={len(bars)} last_close={bars[-1].get('c') if bars else '—'}]")
            continue
        atr_usd, _ = _compute_atr(bars[-15:])
        if atr_usd < _MIN_ATR_DOLLARS:
            n_atr_fail += 1
            continue
        one_bar_vol = avg_daily_vol / 78
        elapsed_pct = min(elapsed_min / 390.0, 1.0)
        expected_vol = max(avg_daily_vol * elapsed_pct, one_bar_vol)
        rvol = c["daily_vol"] / expected_vol if expected_vol > 0 else 0.0
        rvol_min = _MIN_RVOL_ETF if ticker in _ETF_SET else _MIN_RVOL
        if elapsed_min >= 5:
            rvol_ok = rvol >= rvol_min
        else:
            rvol_ok = c["daily_vol"] >= one_bar_vol
        if not rvol_ok:
            n_rvol_fail += 1
            print(f"    {ticker}: daily_vol={c['daily_vol']:.0f} avg_vol={avg_daily_vol:.0f} "
                  f"rvol={rvol:.2f} (need {rvol_min}) -> REJECTED")
            continue
        scored.append((ticker, rvol, c["abs_gap"], atr_usd))

    print(f"\nStage 4 — daily bars available: {len(candidates) - n_bars_fail}/{len(candidates)} "
          f"({n_bars_fail} failed)")
    print(f"Stage 5 — avg 20d volume >= {_MIN_AVG_DAILY_VOL:,}: {n_vol_fail} rejected")
    print(f"Stage 6 — ATR(14) >= ${_MIN_ATR_DOLLARS}: {n_atr_fail} rejected")
    print(f"Stage 7 — RVOL check: {n_rvol_fail} rejected (see per-ticker detail above)")
    print(f"\n=> FINAL scan_details count: {len(scored)}")
    if scored:
        for t, r, g, a in scored:
            print(f"   {t}: rvol={r:.2f} gap={g:.2f}% atr=${a:.2f}")
    else:
        print("   Empty — matches what daily_universe.json shows. See which stage "
              "ate all the candidates above to know where to look next.")


if __name__ == "__main__":
    main()
