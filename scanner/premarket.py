"""
scanner/premarket.py — daily_premarket_scan: the full dynamic universe
builder that runs once each trading day at/after 9:30 ET (gap/price/volume/
ATR/RVOL filtering across LIQUID_POOL, writing the top N to disk).

Split out of the old single scanner.py (2026-08-01, file-size cleanup); no
logic changed, only relocated.

Kept as ONE function rather than split further: it is a single ordered
filter-and-select pipeline (fetch snapshots -> gap filter -> price/volume
filter -> ATR filter -> RVOL filter -> rank -> fallback to anchors if too
few pass -> write to disk) where each stage's placement is load-bearing —
the same "irreducible sequential function" exception used elsewhere in this
refactor (e.g. broker/alpaca_bars.py's get_session_bars).
"""

import json
import logging
import time

from config import TICKER_UNIVERSE
from market_data import get_consolidated_daily_bars
from scanner.constants import (
    ANCHOR_TICKERS, LIQUID_POOL, TICKER_BLACKLIST, _ETF_SET,
    _MAX_GAP_PCT, _MIN_ATR_DOLLARS, _MIN_AVG_DAILY_VOL, _MIN_GAP_PCT,
    _MIN_GAP_PCT_ETF, _MIN_PRICE, _MIN_RVOL, _MIN_RVOL_ETF,
)
from scanner.helpers import _compute_atr, _et_now
from scanner.state_io import _read_daily_universe, _write_daily_universe, _write_state
from scanner.universe import build_collection_universe

logger = logging.getLogger("celo_trader.scanner")

def daily_premarket_scan(alpaca, max_tickers: int = 10, force: bool = False) -> list[str]:
    """
    Full dynamic universe scan — runs once each trading day at/after 9:30 ET.

    Pipeline
    ────────
    1. Batch-fetch Alpaca snapshots for all LIQUID_POOL tickers (batches of 50).
    2. Filter: price > $10, abs(open_gap) between 1 % and 4 %.
    3. Fetch 22 daily bars for each gap survivor.
    4. Filter: avg_daily_vol > 2 M, ATR(14) > $1.
    5. Compute RVOL vs time-normalized expected volume.
    6. Score: RVOL × gap_pct × atr_factor × liquidity_bonus.
    7. Return user pins + anchors + the top max_tickers dynamic candidates.
    8. Write results to daily_universe.json + scanner_state.json.

    If called before 9:30 ET (pre-market), skips the scan and returns ANCHOR_TICKERS
    as a fallback — the open price isn't available yet to compute a reliable gap.
    """
    et_now = _et_now()
    today_str = et_now.strftime("%Y-%m-%d")

    # Guard: need the open bar for reliable gap calculation.
    # Pass force=True to bypass this guard (e.g. manual /api/market/scan-now trigger).
    session_open_min = 9 * 60 + 30
    current_min      = et_now.hour * 60 + et_now.minute
    if current_min < session_open_min and not force:
        logger.info(
            "daily_premarket_scan: pre-market (%02d:%02d ET) — "
            "skipping until session open", et_now.hour, et_now.minute,
        )
        # Return yesterday's universe or anchors as a placeholder
        prev = _read_daily_universe()
        return prev.get("universe") or list(ANCHOR_TICKERS)

    # Minutes elapsed since 9:30 (at least 1 to avoid division by zero)
    elapsed_min = max(1.0, current_min - session_open_min)

    logger.info(
        "daily_premarket_scan: scanning %d pool tickers (+%d min since open)",
        len(LIQUID_POOL), int(elapsed_min),
    )

    # ── Inject user-pinned tickers from Settings watchlist ───────────────────
    # Tickers the user pinned in Settings > Watchlist are always evaluated and
    # always appear in the final list. They bypass the gap/RVOL filters so the
    # user's explicit watchlist remains visible to the approved strategy catalog.
    try:
        from config import get_settings as _get_s
        _user_pins = [
            t.upper().strip()
            for t in (_get_s().get("watchlist") or [])
            if t.strip() and t.strip().upper() not in TICKER_BLACKLIST
        ]
    except Exception:
        _user_pins = []

    # ── Step 1: Batch snapshots ───────────────────────────────────────────────
    # Merge user-pinned tickers into the pool so they get snapshot data too.
    pool = list(dict.fromkeys(                          # deduplicate, preserve order
        [t for t in LIQUID_POOL if t not in TICKER_BLACKLIST]
        + _user_pins
    ))
    all_snaps: dict[str, dict] = {}
    batch_size = 50
    for i in range(0, len(pool), batch_size):
        batch = pool[i : i + batch_size]
        try:
            snaps = alpaca.get_snapshots(batch)
            all_snaps.update(snaps)
        except Exception as ex:
            logger.warning("daily_premarket_scan: snapshot batch %d failed: %s",
                           i // batch_size, ex)

    logger.info("daily_premarket_scan: got snapshots for %d tickers", len(all_snaps))

    # ── Step 2: Price + gap filter ────────────────────────────────────────────
    candidates = []
    for ticker, snap in all_snaps.items():
        price      = snap.get("price", 0) or 0
        prev_close = snap.get("prev_close", 0) or 0
        open_price = snap.get("open_price", 0) or 0
        daily_vol  = snap.get("daily_vol", 0) or 0

        if price < _MIN_PRICE:
            continue

        # Gap = open vs previous close (open_price=0 means market not yet open)
        gap_ref = open_price if open_price > 1.0 else price
        if prev_close <= 0:
            continue
        gap_pct = (gap_ref - prev_close) / prev_close * 100
        abs_gap  = abs(gap_pct)

        # ETFs gap less than stocks by nature — use a lower minimum gap threshold
        _gap_min = _MIN_GAP_PCT_ETF if ticker in _ETF_SET else _MIN_GAP_PCT
        if abs_gap < _gap_min or abs_gap > _MAX_GAP_PCT:
            logger.debug("%s gap=%.2f%% outside [%.2f%%–%.0f%%] — skipped",
                         ticker, gap_pct, _gap_min, _MAX_GAP_PCT)
            continue

        candidates.append({
            "ticker":    ticker,
            "price":     price,
            "gap_pct":   round(gap_pct, 3),
            "abs_gap":   round(abs_gap, 3),
            "gap_dir":   "up" if gap_pct >= 0 else "down",
            "daily_vol": daily_vol,
            "prev_close": prev_close,
        })

    logger.info("daily_premarket_scan: %d tickers passed price+gap filter",
                len(candidates))

    # ── Steps 3-6: Daily bars → avg vol, ATR, RVOL, score ────────────────────
    #
    # FIX 2026-07-28: this used to call Alpaca's daily-bar endpoint (IEX feed)
    # first and only fall back to yfinance if Alpaca was entirely down. That
    # meant avg_daily_vol was almost always computed from IEX-only volume —
    # a small slice of a stock's real trading volume — compared against
    # _MIN_AVG_DAILY_VOL (2,000,000 real shares). Confirmed live: 60 of 62
    # gap-filtered candidates were wrongly rejected here, including MSFT and
    # QQQ. get_consolidated_daily_bars() (market_data.py) now sources real
    # consolidated volume from yfinance FIRST, falling back to Alpaca per-
    # ticker only if yfinance has no data for that symbol.
    # ──────────────────────────────────────────────────────────────────────────
    _daily_bars_cache = get_consolidated_daily_bars(
        [c["ticker"] for c in candidates], alpaca=alpaca, lookback_days=22,
    )

    scored = []
    for c in candidates:
        ticker = c["ticker"]
        try:
            bars = _daily_bars_cache.get(ticker, [])
            if len(bars) < 10:
                logger.debug(
                    "daily_premarket_scan: %s — insufficient daily bars (%d) — skipped",
                    ticker, len(bars),
                )
                continue

            # 20-day avg daily volume
            vol_bars   = bars[-20:]
            vols       = [float(b.get("v", 0)) for b in vol_bars]
            avg_daily_vol = sum(vols) / len(vols) if vols else 0.0
            if avg_daily_vol < _MIN_AVG_DAILY_VOL:
                logger.debug("%s avg_vol=%.0f < 2M — skipped", ticker, avg_daily_vol)
                continue

            # ATR(14) on daily bars
            atr_usd, _ = _compute_atr(bars[-15:])
            if atr_usd < _MIN_ATR_DOLLARS:
                logger.debug("%s ATR=$%.2f < $1 — skipped", ticker, atr_usd)
                continue

            # ── RVOL vs time-normalized expected volume ───────────────────
            # At 9:31 elapsed_pct = 1/390 = 0.003, making expected_vol tiny
            # and inflating RVOL to 7–10× for virtually every stock (noise).
            elapsed_pct  = min(elapsed_min / 390.0, 1.0)
            one_bar_vol  = avg_daily_vol / 78   # expected shares in one 5-min bar
            expected_vol = max(avg_daily_vol * elapsed_pct, one_bar_vol)
            rvol = c["daily_vol"] / expected_vol if expected_vol > 0 else 0.0

            # ETFs get a lower RVOL bar — they don't spike like individual stocks
            _rvol_min = _MIN_RVOL_ETF if ticker in _ETF_SET else _MIN_RVOL
            if elapsed_min >= 5:
                rvol_ok = rvol >= _rvol_min
            else:
                rvol_ok = c["daily_vol"] >= one_bar_vol  # early: real volume check
            if not rvol_ok:
                logger.debug(
                    "%s RVOL=%.2f < %.1f (vol=%d, exp=%d, elapsed=%.0f min) — skipped",
                    ticker, rvol, _rvol_min, c["daily_vol"], int(expected_vol), elapsed_min,
                )
                continue

            # Composite score: RVOL (capped) × gap magnitude × ATR × ETF bonus
            rvol_capped = min(rvol, 20.0)   # prevent early-session inflation
            liq         = 1.15 if ticker in _ETF_SET else 1.0
            atr_factor  = min(atr_usd / 5.0, 2.0)  # caps contribution at 2×
            score = rvol_capped * c["abs_gap"] * atr_factor * liq

            # ── Affordability filter: de-rank tickers that would always bust the
            # position-size budget. Estimate: ATM option premium ≈ 0.5 × daily ATR.
            #
            # FIX 2026-07-24: this used to compare against risk_pct/risk_per_trade
            # (the per-trade LOSS budget from the 4-tier sizing system) — but the
            # real live entry gate (trading/entry.py::_place_entry, "over_budget"
            # check) compares the FULL contract premium against max_position_dollars_pct
            # (or max_position_dollars), a completely different setting. That
# This must mirror the real gate: full estimated premium × 100 shares vs.
# the same max_position_dollars_pct/max_position_dollars budget.
            try:
                from config import get_settings as _get_s_aff
                _s_aff = _get_s_aff()
                _bal      = float(_s_aff.get("last_known_balance", 1000.0))
                _cap_pct  = _s_aff.get("max_position_dollars_pct")
                if _cap_pct:
                    _budget = _bal * (float(_cap_pct) / 100.0)
                else:
                    _budget = float(_s_aff.get("max_position_dollars", 750.0))
                _est_premium       = atr_usd * 0.5             # rough ATM premium estimate
                _est_contract_cost = _est_premium * 100.0       # full premium, 1 contract
                if _budget > 0 and _est_contract_cost > _budget:
                    score *= 0.05   # 95% penalty — bot can't afford even 1 contract
                    logger.debug(
                        "%s affordability penalty: est_premium=$%.2f → contract_cost=$%.2f "
                        "> budget=$%.2f (max_position_dollars_pct=%s, balance=$%.0f) → score de-ranked",
                        ticker, _est_premium, _est_contract_cost, _budget, _cap_pct, _bal,
                    )
            except Exception:
                pass  # non-critical — scoring still runs without affordability check

            scored.append({
                **c,
                "avg_daily_vol": int(avg_daily_vol),
                "atr_usd":       round(atr_usd, 2),
                "rvol":          round(rvol, 2),
                "rvol_capped":   round(rvol_capped, 2),
                "score":         round(score, 6),
            })

        except Exception as ex:
            logger.warning("daily_premarket_scan: error processing %s: %s", ticker, ex)

    # ── Sort and trim ─────────────────────────────────────────────────────────
    scored.sort(key=lambda x: x["score"], reverse=True)
    dynamic_top = [s["ticker"] for s in scored[:max_tickers]]

    logger.info(
        "daily_premarket_scan: %d survived all filters → top%d: %s",
        len(scored), max_tickers, dynamic_top,
    )

    # The Daily Brief exposes the top-N dynamic rows in ``scan_details``. Pins
    # and anchors used to displace most of those rows from ``top``, so the UI
    # could show a candidate whose one-minute candles and strategy outcomes
    # were never collected. Keep all three groups in the runtime universe.
    top = build_collection_universe(
        user_pins=_user_pins,
        dynamic_tickers=dynamic_top,
    )
    logger.info(
        "daily_premarket_scan: collection universe has %d ticker(s): %s",
        len(top), top,
    )

    # ── Persist results ───────────────────────────────────────────────────────
    _write_daily_universe(today_str, top, scored[:max_tickers])
    scores_dict = {s["ticker"]: s["score"] for s in scored}
    _write_state(top, scores_dict)

    return top
