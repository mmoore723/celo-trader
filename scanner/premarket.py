"""Broad optionable-universe scanner and strategy-aware daily shortlist."""

import logging
import math

from market_data import get_consolidated_daily_bars
from scanner.constants import (
    ANCHOR_TICKERS, LIQUID_POOL, TICKER_BLACKLIST, _ETF_SET,
    _MIN_ATR_DOLLARS, _MIN_AVG_DAILY_VOL, _MIN_GAP_PCT,
    _MIN_GAP_PCT_ETF, _MIN_PRICE, _MIN_RVOL, _MIN_RVOL_ETF,
)
from scanner.helpers import _compute_atr, _et_now
from scanner.state_io import _write_daily_universe, _write_state
from scanner.universe import build_collection_universe

logger = logging.getLogger("celo_trader.scanner")

SNAPSHOT_BATCH_SIZE = 200
BROAD_PREFILTER_LIMIT = 180


def _optionable_scan_pool(alpaca, user_pins: list[str]) -> tuple[list[str], str]:
    """Load the live optionable universe, with the reviewed pool as fallback."""
    try:
        discovered = alpaca.get_optionable_assets()
    except Exception as ex:
        logger.warning("daily_premarket_scan: optionable asset discovery failed: %s", ex)
        discovered = []
    source = "Alpaca active optionable assets" if discovered else "reviewed fallback pool"
    pool = list(dict.fromkeys(
        [ticker for ticker in discovered or LIQUID_POOL if ticker not in TICKER_BLACKLIST]
        + list(ANCHOR_TICKERS)
        + user_pins
    ))
    return pool, source


def _strategy_fit_labels(bars: list[dict], *, gap_pct: float, atr_usd: float, price: float) -> list[str]:
    """Describe which existing strategy families made a ticker worth keeping."""
    labels: list[str] = []
    ranges = [max(0.0, float(row.get("h", 0)) - float(row.get("l", 0))) for row in bars[-7:]]
    if ranges and ranges[-1] <= min(ranges):
        labels.append("compressed-range ORB")
    if len(bars) >= 2:
        prior, latest = bars[-2], bars[-1]
        if float(latest.get("h", 0)) <= float(prior.get("h", 0)) and float(latest.get("l", 0)) >= float(prior.get("l", 0)):
            labels.append("inside-day ORB")
    atr_pct = atr_usd / price * 100 if price > 0 else 0.0
    if abs(gap_pct) >= 0.5 and atr_pct >= 1.0:
        labels.append("trend / pullback")
    if atr_pct >= 2.0:
        labels.append("volatility")
    return labels or ["liquid options candidate"]


def _balanced_shortlist(scored: list[dict], max_tickers: int) -> list[dict]:
    """Keep strong candidates from each existing strategy family."""
    if max_tickers <= 0:
        return []
    families = ("compressed-range ORB", "inside-day ORB", "trend / pullback", "volatility")
    chosen: list[dict] = []
    seen: set[str] = set()
    per_family = max(1, max_tickers // len(families))
    for family in families:
        for row in (item for item in scored if family in item.get("strategy_fit", [])):
            if row["ticker"] in seen:
                continue
            chosen.append(row)
            seen.add(row["ticker"])
            if sum(family in item.get("strategy_fit", []) for item in chosen) >= per_family:
                break
    for row in scored:
        if len(chosen) >= max_tickers:
            break
        if row["ticker"] not in seen:
            chosen.append(row)
            seen.add(row["ticker"])
    return chosen[:max_tickers]


def daily_premarket_scan(alpaca, max_tickers: int = 30, force: bool = False) -> list[str]:
    """
    Full dynamic universe scan — selects the morning universe once per day.

    Pipeline
    ────────
    1. Discover active optionable underlyings and batch-fetch their snapshots.
    2. Reduce thousands of symbols to the most active liquid candidates.
    3. Fetch 22 daily bars for each gap survivor.
    4. Filter: avg_daily_vol > 2 M, ATR(14) > $1.
    5. Compute RVOL vs time-normalized expected volume.
    6. Score: RVOL × gap_pct × atr_factor × liquidity_bonus.
    7. Return user pins + anchors + the top max_tickers dynamic candidates.
    8. Write results to daily_universe.json + scanner_state.json.

    Premarket uses latest price versus prior close. An explicit manual scan can
    use the official opening price, but the automatic trading loop never
    replaces the saved morning selection after the opening bell.
    """
    et_now = _et_now()
    today_str = et_now.strftime("%Y-%m-%d")

    session_open_min = 9 * 60 + 30
    current_min      = et_now.hour * 60 + et_now.minute
    scan_phase = "premarket" if current_min < session_open_min and not force else "regular"

    # Minutes elapsed since 9:30 (at least 1 to avoid division by zero)
    elapsed_min = max(1.0, current_min - session_open_min)

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

    # ── Step 1: Discover and snapshot the full optionable universe ────────────
    pool, source = _optionable_scan_pool(alpaca, _user_pins)
    logger.info("daily_premarket_scan: %s contains %d symbols", source, len(pool))
    all_snaps: dict[str, dict] = {}
    for i in range(0, len(pool), SNAPSHOT_BATCH_SIZE):
        batch = pool[i : i + SNAPSHOT_BATCH_SIZE]
        try:
            snaps = alpaca.get_snapshots(batch)
            all_snaps.update(snaps)
        except Exception as ex:
            logger.warning("daily_premarket_scan: snapshot batch %d failed: %s",
                           i // SNAPSHOT_BATCH_SIZE, ex)

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

        # Premarket has no official open yet, so use the latest extended-hours
        # price. After 9:30 use today's opening print.
        gap_ref = price if scan_phase == "premarket" else (open_price if open_price > 1.0 else price)
        if prev_close <= 0:
            continue
        gap_pct = (gap_ref - prev_close) / prev_close * 100
        abs_gap  = abs(gap_pct)

        # A broad screen needs more than large gappers: compressed ORB and
        # pullback strategies can be valid on smaller opening moves.
        _gap_min = _MIN_GAP_PCT_ETF if ticker in _ETF_SET else _MIN_GAP_PCT
        discovery_floor = min(_gap_min, 0.25 if ticker in _ETF_SET else 0.50)
        if abs_gap < discovery_floor and ticker not in _user_pins and ticker not in ANCHOR_TICKERS:
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

    # Bound the expensive daily-history step while retaining both large movers
    # and liquid names. This is a screen of the entire universe, not a fixed list.
    candidates.sort(
        key=lambda row: (
            row["abs_gap"] * 3.0 + math.log10(max(1, row["daily_vol"])),
            row["daily_vol"],
        ),
        reverse=True,
    )
    candidates = candidates[:BROAD_PREFILTER_LIMIT]
    logger.info("daily_premarket_scan: %d symbols reached the daily-history screen", len(candidates))

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
            if scan_phase == "premarket":
                rvol_ok = True
                rvol = max(0.25, rvol)
            elif elapsed_min >= 5:
                rvol_ok = rvol >= _rvol_min
            else:
                rvol_ok = c["daily_vol"] >= one_bar_vol  # early: real volume check
            # RVOL is a ranking input, not a universal veto. The individual
            # strategies apply their own entry gates after collection.

            # Composite score: RVOL (capped) × gap magnitude × ATR × ETF bonus
            rvol_capped = min(rvol, 20.0)   # prevent early-session inflation
            liq         = 1.15 if ticker in _ETF_SET else 1.0
            atr_factor  = min(atr_usd / 5.0, 2.0)  # caps contribution at 2×
            liquidity_factor = min(2.0, max(0.6, math.log10(max(avg_daily_vol, 1)) / 4.0))
            activity_factor = max(0.35, rvol_capped if rvol_ok else rvol_capped * 0.5)
            score = activity_factor * (0.5 + min(c["abs_gap"], 12.0)) * atr_factor * liq * liquidity_factor

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
                    score *= 0.50   # still research it; contract selection owns the real gate
                    logger.debug(
                        "%s affordability penalty: est_premium=$%.2f → contract_cost=$%.2f "
                        "> budget=$%.2f (max_position_dollars_pct=%s, balance=$%.0f) → score reduced",
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
                "strategy_fit":  _strategy_fit_labels(
                    bars, gap_pct=c["gap_pct"], atr_usd=atr_usd, price=c["price"],
                ),
            })

        except Exception as ex:
            logger.warning("daily_premarket_scan: error processing %s: %s", ticker, ex)

    # ── Sort and trim ─────────────────────────────────────────────────────────
    scored.sort(key=lambda x: x["score"], reverse=True)
    selected = _balanced_shortlist(scored, max_tickers)
    dynamic_top = [s["ticker"] for s in selected]

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
    _write_daily_universe(today_str, top, selected, {
        "phase": scan_phase,
        "source": source,
        "source_universe_size": len(pool),
        "snapshots_received": len(all_snaps),
        "daily_history_screened": len(candidates),
        "research_candidates": len(dynamic_top),
    })
    scores_dict = {s["ticker"]: s["score"] for s in scored}
    _write_state(top, scores_dict)

    return top
