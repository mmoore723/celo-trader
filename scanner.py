"""
scanner.py — Dynamic daily universe builder + intra-session rescore.

Two-phase operation
───────────────────
Phase 1  (first call after 9:30 ET each day):
    daily_premarket_scan() fetches snapshots for the entire LIQUID_POOL (~150
    tickers), filters by open-gap / price / avg-volume / ATR / RVOL, and writes
    the top 10 "stocks in play" to scanner_state.json + daily_universe.json.

Phase 2  (every subsequent run_scan() call during the session):
    Rescores the already-selected 10-ticker universe by live RVOL × momentum so
    the trading loop can always evaluate the hottest mover first.

Scoring formula (Phase 2 rescore):
    RVOL × |momentum_pct| × liquidity_bonus

Dynamic scan criteria (Phase 1, per advice):
    price          > $10
    avg daily vol  > 2 M  (20-day SMA)
    ATR(14)        > $1   (enough meat on the bone)
    open gap       1 % – 4 %  (either direction)
    early RVOL     ≥ 2.5 ×  (relaxed before 5 min into session)
"""

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from config import TICKER_UNIVERSE, BASE_DIR

logger = logging.getLogger("celo_trader.scanner")

SCANNER_STATE      = BASE_DIR / "scanner_state.json"
DAILY_UNIVERSE_PATH = BASE_DIR / "daily_universe.json"

# ── ETF set — liquidity bonus in scoring ──────────────────────────────────────
_ETF_SET = {"SPY", "QQQ", "IWM", "DIA", "XLE", "GLD",
            "XLK", "XLF", "XLV", "XLY", "XLI", "XLB", "XLC",
            "SMH"}   # VanEck Semiconductor ETF — deep options, high gap freq

# ── Hard blacklist — leveraged/inverse ETFs, VIX products ────────────────────
# TSLT (2× TSLA), TSLL (1.5× TSLA), NVDL (2× NVDA) etc. are explicitly
# blocked — the leverage multiplier inflates RVOL scores artificially, and
# their option chains are thin or absent on Tradier's free tier.
TICKER_BLACKLIST: set[str] = {
    "SQQQ", "TQQQ", "SPXS", "SPXU", "UPRO", "SDS", "SSO",
    "UVXY", "SVXY", "VXX", "VIXY", "LABD", "LABU",
    "SOXS", "SOXL", "TECL", "TECS", "FNGU", "FNGD",
    "SDOW", "UDOW", "SRTY", "URTY",
    # Single-stock leveraged ETFs (commonly appear as high-RVOL names)
    "TSLT", "TSLL", "NVDL", "NVDU", "MSFU", "AAPU", "AMZU",
    "METL", "CONL", "MSFO",
}

# ── Dynamic scan pool: ~140 liquid, optionable US stocks ─────────────────────
# Every ticker in this list must be able to pass the gap + volume + ATR filters
# on an active day. Names that structurally can't gap 1-4% (bond ETFs, REITs,
# low-beta telecoms) or that trade consistently below $10 (SOFI, LCID) are
# excluded here — they waste API quota every morning.
#
# REMOVED vs. first draft:
#   TLT, HYG, LQD — bond ETFs; almost never gap 1-4% on normal days
#   SLV            — lower volume/liquidity than GLD; redundant
#   AMT, PLD, EQIX — REITs; slow movers, no ORB edge
#   T, VZ          — telecom stalwarts; historically < 0.5% beta, rarely gap
#   SOFI, LCID     — trade below $10; always fail the price filter
#
# ADDED:
#   SMH  — VanEck Semiconductor ETF; high volume, deep options, gaps on macro
#   GME  — gaps frequently on news/options flow with >5× RVOL; meets all filters
LIQUID_POOL: list[str] = [
    # ── Index + sector ETFs ───────────────────────────────────────────────
    # Deep options chains, penny-wide spreads on Tradier free tier.
    # SPY/QQQ are anchors — always in the fallback even if they don't gap.
    "SPY", "QQQ", "IWM", "DIA",
    "XLK", "XLF", "XLE", "XLV", "XLY", "XLI", "XLB", "XLC",
    "GLD",           # gold — gaps on macro/CPI/FOMC surprises
    "SMH",           # VanEck Semiconductors — gaps on AI/chip news

    # ── Mega-cap tech ──────────────────────────────────────────────────────
    # Institutional volume ensures > 2M daily shares and deep option OI.
    "AAPL", "MSFT", "NVDA", "AMD", "META", "GOOGL", "GOOG", "AMZN",
    "TSLA", "NFLX", "INTC", "QCOM", "AVGO", "TXN", "MU", "AMAT",
    "LRCX", "KLAC", "MRVL", "SMCI", "ARM",

    # ── Financials ────────────────────────────────────────────────────────
    # Gap frequently on Fed announcements, earnings, and macro data.
    "JPM", "BAC", "WFC", "GS", "MS", "C", "V", "MA", "AXP", "PYPL",
    "COF", "USB", "PNC", "SCHW", "BLK", "SPGI",

    # ── Healthcare / Biotech ──────────────────────────────────────────────
    # Drug approvals and clinical trial results produce clean 1-4% gap setups.
    "UNH", "PFE", "MRK", "ABBV", "LLY", "AMGN", "GILD",
    "MRNA", "BNTX", "VRTX", "REGN", "BIIB", "CVS", "CI", "HCA",

    # ── Energy ────────────────────────────────────────────────────────────
    # Oil price moves and inventory reports create strong ORB gaps.
    "XOM", "CVX", "COP", "EOG", "SLB", "HAL", "OXY", "DVN",

    # ── Consumer Discretionary ────────────────────────────────────────────
    "WMT", "TGT", "HD", "LOW", "COST", "MCD", "SBUX", "NKE",
    "DIS", "CMCSA", "ABNB", "BKNG", "CCL", "F", "GM",

    # ── Communication / Media ─────────────────────────────────────────────
    # TMUS stays (high enough volume); SNAP/PINS kept for news-driven gaps.
    "TMUS", "SNAP", "PINS", "ROKU",

    # ── Industrials / Transport ───────────────────────────────────────────
    "BA", "CAT", "GE", "HON", "RTX", "LMT", "NOC", "DE",
    "UPS", "FDX", "UBER", "LYFT",

    # ── High-beta "stocks in play" ────────────────────────────────────────
    # These are the PRIMARY targets: gap 1-4% + RVOL > 2.5× is common here.
    # Each name regularly attracts institutional options flow at the open.
    "PLTR", "RIVN", "DKNG", "COIN", "MARA", "RIOT",
    "MSTR", "HOOD", "SQ", "AFRM", "UPST", "RBLX", "U", "NET",
    "CRWD", "PANW", "OKTA", "SNOW", "DDOG", "ZS", "MDB", "CFLT",
    "TWLO", "ZM", "DOCU",
    "GME",           # meme stock — gaps with >5× RVOL on Reddit/news flow

    # ── Semiconductors (individual names) ─────────────────────────────────
    "TSM", "ASML", "MCHP", "ON", "SWKS",
]

# ── Fallback anchor tickers if scan finds < 2 stocks ─────────────────────────
ANCHOR_TICKERS = ["SPY", "QQQ"]

# ── Backward-compat alias used by dashboard.py ───────────────────────────────
SCAN_UNIVERSE = list(TICKER_UNIVERSE)   # kept so old reads don't KeyError

# ── Timing windows (ET) ───────────────────────────────────────────────────────
PREMARKET_START_HM = (9, 0)
PREMARKET_END_HM   = (9, 29)
SESSION_START_HM   = (9, 30)
SESSION_END_HM     = (11, 30)

# ── Dynamic scan thresholds ───────────────────────────────────────────────────
_MIN_PRICE         = 10.0        # minimum stock price
_MIN_AVG_DAILY_VOL = 2_000_000   # 20-day avg daily share volume
_MIN_GAP_PCT       = 1.0         # open must gap at least 1 % from prev close
_MAX_GAP_PCT       = 4.0         # cap at 4 % to avoid over-extended names
_MIN_RVOL          = 2.5         # early-session RVOL vs normalized avg
_MIN_ATR_DOLLARS   = 1.0         # ATR(14) on daily bars must be > $1

# Legacy intra-session ATR thresholds (used by _score_ticker rescore)
_ATR_MIN_DOLLARS = 1.50
_ATR_MIN_PCT     = 0.015


# ── Helpers ───────────────────────────────────────────────────────────────────

def _et_now() -> datetime:
    """Return current Eastern Time as a naive datetime (UTC−4 approximation)."""
    from datetime import timedelta
    return datetime.utcnow() - timedelta(hours=4)


def _hm_in_range(hour: int, minute: int,
                 start: tuple[int, int], end: tuple[int, int]) -> bool:
    val = hour * 60 + minute
    lo  = start[0] * 60 + start[1]
    hi  = end[0]   * 60 + end[1]
    return lo <= val <= hi


def _compute_atr(bars: list[dict]) -> tuple[float, float]:
    """
    Return (atr_dollars, atr_pct) for the last 14 bars.
    atr_pct = atr_dollars / last_close.
    Returns (0.0, 0.0) if bars insufficient.
    """
    if len(bars) < 2:
        return 0.0, 0.0
    trs = []
    for i in range(1, len(bars)):
        h  = float(bars[i].get("h", 0))
        l  = float(bars[i].get("l", 0))
        pc = float(bars[i - 1].get("c", bars[i].get("c", 0)))
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    atr_dollars = sum(trs[-14:]) / min(len(trs), 14)
    last_close  = float(bars[-1].get("c", 0))
    atr_pct     = atr_dollars / last_close if last_close > 0 else 0.0
    return round(atr_dollars, 4), round(atr_pct, 6)


def _score_ticker(bars: list[dict], ticker: str) -> float:
    """
    Intra-session rescore: RVOL × momentum × liquidity bonus.
    Used for Phase 2 re-ranking within the already-selected universe.
    Returns 0.0 if bars are insufficient or ATR is too low.
    """
    if not bars or len(bars) < 5:
        return 0.0

    atr_usd, atr_pct = _compute_atr(bars)
    if atr_usd < _ATR_MIN_DOLLARS and atr_pct < _ATR_MIN_PCT:
        logger.debug(
            "Scanner rescore: %s ATR=$%.2f (%.2f%%) below thresholds — score=0",
            ticker, atr_usd, atr_pct * 100,
        )
        return 0.0

    volumes = [float(b.get("v", 0)) for b in bars]
    avg_vol = sum(volumes[:-1]) / max(len(volumes) - 1, 1)
    cur_vol = volumes[-1]
    rvol    = cur_vol / avg_vol if avg_vol > 0 else 0.0

    try:
        first_open = float(bars[0].get("o", bars[0].get("c", 0)))
        last_close = float(bars[-1].get("c", 0))
        momentum   = abs(last_close - first_open) / first_open if first_open > 0 else 0.0
    except (TypeError, ZeroDivisionError):
        momentum = 0.0

    liquidity = 1.15 if ticker in _ETF_SET else 1.0
    return round(rvol * momentum * liquidity, 6)


# ── Public API ────────────────────────────────────────────────────────────────

def run_scan(alpaca, max_tickers: int = 10) -> list[str]:
    """
    Entry point called by trading_logic._tick() and _evaluate_signals().

    First call of the session (after 9:30 ET):
        Runs daily_premarket_scan() — full pool scan, gap+RVOL filtering,
        writes today's universe to disk.

    Subsequent calls:
        Rescores the already-selected universe by live 5-min RVOL × momentum so
        the hottest mover is evaluated first each tick.

    Returns a list of ticker strings, highest priority first.
    """
    today_str = _et_now().strftime("%Y-%m-%d")
    daily     = _read_daily_universe()

    # ── Phase 1: full scan (once per session, after market open) ─────────────
    if daily.get("date") != today_str or not daily.get("universe"):
        logger.info("run_scan: no fresh daily universe — triggering daily_premarket_scan")
        return daily_premarket_scan(alpaca, max_tickers)

    # ── Phase 2: rescore existing dynamic universe ────────────────────────────
    # Always include user-pinned tickers even if they weren't in today's scan.
    try:
        from config import get_settings as _get_s2
        _pins2 = [
            t.upper().strip()
            for t in (_get_s2().get("watchlist") or [])
            if t.strip() and t.strip().upper() not in TICKER_BLACKLIST
        ]
    except Exception:
        _pins2 = []

    current_universe = list(dict.fromkeys(_pins2 + daily["universe"]))

    scores: dict[str, float] = {}
    for ticker in current_universe:
        try:
            bars, err = alpaca.get_bars(ticker, "5Min", limit=25)
            if err or not bars:
                scores[ticker] = 0.0
                continue
            scores[ticker] = _score_ticker(bars, ticker)
        except Exception as ex:
            logger.warning("Scanner rescore error for %s: %s", ticker, ex)
            scores[ticker] = 0.0

    ranked = sorted(scores, key=lambda t: scores[t], reverse=True)
    # Pinned tickers always lead the list regardless of their score
    watchlist = _pins2 + [t for t in ranked if t not in TICKER_BLACKLIST and t not in _pins2]
    if not watchlist:
        watchlist = [t for t in current_universe if t not in TICKER_BLACKLIST]
    if not watchlist:
        watchlist = list(ANCHOR_TICKERS)

    _write_state(watchlist, scores)
    logger.info(
        "scan_rescore",
        extra={"event": "scan_rescore", "watchlist": watchlist,
               "top_scores": {t: scores.get(t, 0) for t in watchlist[:5]}},
    )
    return watchlist


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
    7. Return top max_tickers, always padding with ANCHOR_TICKERS if < 2 found.
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
    # always appear in the final list — they bypass the gap/RVOL filters so a
    # slower mover the user wants tracked doesn't get silently dropped.
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

        if abs_gap < _MIN_GAP_PCT or abs_gap > _MAX_GAP_PCT:
            logger.debug("%s gap=%.2f%% outside [%.0f%%–%.0f%%] — skipped",
                         ticker, gap_pct, _MIN_GAP_PCT, _MAX_GAP_PCT)
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
    # Probe Alpaca daily bars once before the per-ticker loop.
    # When the circuit breaker is open, ALL individual get_bars("1Day") calls
    # return ([], True) — causing 0 survivors even though snapshots succeeded.
    # Fix: if the probe fails, batch-download daily bars for ALL candidates via
    # yfinance in one shot (~1 s for 40 tickers) and use that as the source.
    # ──────────────────────────────────────────────────────────────────────────
    _yf_daily_cache: dict[str, list[dict]] = {}
    _probe_bars, _probe_err = alpaca.get_bars("SPY", "1Day", limit=3)
    if _probe_err or not _probe_bars:
        logger.info(
            "daily_premarket_scan: Alpaca daily bars unavailable (probe failed) "
            "— batch-downloading daily OHLCV from yfinance for %d candidates",
            len(candidates),
        )
        try:
            import yfinance as yf
            import datetime as _dt
            _cand_tickers = [c["ticker"] for c in candidates]
            _end_d   = _dt.date.today() + _dt.timedelta(days=1)
            _start_d = _end_d - _dt.timedelta(days=40)
            _yf_batch = yf.download(
                _cand_tickers,
                start=_start_d.strftime("%Y-%m-%d"),
                end=_end_d.strftime("%Y-%m-%d"),
                interval="1d",
                progress=False,
                auto_adjust=True,
                group_by="ticker",
            )
            for _t in _cand_tickers:
                try:
                    # Multi-ticker download returns a MultiIndex DataFrame;
                    # single-ticker returns a plain DataFrame.
                    _df = _yf_batch if len(_cand_tickers) == 1 else _yf_batch[_t]
                    if _df is None or _df.empty:
                        continue
                    # Flatten MultiIndex columns (yfinance ≥ 0.2)
                    if hasattr(_df.columns, "get_level_values"):
                        _df.columns = _df.columns.get_level_values(0)
                    _yf_daily_cache[_t] = [
                        {
                            "o": float(r.get("Open",   0) or 0),
                            "h": float(r.get("High",   0) or 0),
                            "l": float(r.get("Low",    0) or 0),
                            "c": float(r.get("Close",  0) or 0),
                            "v": float(r.get("Volume", 0) or 0),
                        }
                        for _, r in _df.iterrows()
                        if float(r.get("Close", 0) or 0) > 0
                    ]
                except Exception:
                    pass
            logger.info(
                "daily_premarket_scan: yfinance batch loaded daily bars for %d/%d tickers",
                len(_yf_daily_cache), len(_cand_tickers),
            )
        except Exception as _yf_ex:
            logger.warning(
                "daily_premarket_scan: yfinance batch daily download failed: %s", _yf_ex
            )

    scored = []
    for c in candidates:
        ticker = c["ticker"]
        try:
            bars, err = alpaca.get_bars(ticker, "1Day", limit=22)
            # If Alpaca failed, fall back to the yfinance batch cache
            if err or len(bars) < 10:
                bars = _yf_daily_cache.get(ticker, [])
                err  = len(bars) < 10
            if err or len(bars) < 10:
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
            # Fix:
            #   1. Floor expected_vol at 1 five-min bar (avg_daily_vol / 78)
            #      so the denominator is never unrealistically small.
            #   2. After 5 min: require RVOL >= 2.5× (real threshold).
            #      Before 5 min: require at least 1 full five-min bar's worth of
            #      shares traded (any real activity, not stray prints).
            #   3. Cap RVOL at 20× for the score so early-session spikes don't
            #      dominate gap_pct and ATR in the ranking.
            elapsed_pct  = min(elapsed_min / 390.0, 1.0)
            one_bar_vol  = avg_daily_vol / 78   # expected shares in one 5-min bar
            expected_vol = max(avg_daily_vol * elapsed_pct, one_bar_vol)
            rvol = c["daily_vol"] / expected_vol if expected_vol > 0 else 0.0

            if elapsed_min >= 5:
                rvol_ok = rvol >= _MIN_RVOL
            else:
                rvol_ok = c["daily_vol"] >= one_bar_vol  # early: real volume check
            if not rvol_ok:
                logger.debug(
                    "%s RVOL=%.2f (vol=%d, exp=%d, elapsed=%.0f min) — skipped",
                    ticker, rvol, c["daily_vol"], int(expected_vol), elapsed_min,
                )
                continue

            # Composite score: RVOL (capped) × gap magnitude × ATR × ETF bonus
            rvol_capped = min(rvol, 20.0)   # prevent early-session inflation
            liq         = 1.15 if ticker in _ETF_SET else 1.0
            atr_factor  = min(atr_usd / 5.0, 2.0)  # caps contribution at 2×
            score = rvol_capped * c["abs_gap"] * atr_factor * liq

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
    top = [s["ticker"] for s in scored[:max_tickers]]

    logger.info(
        "daily_premarket_scan: %d survived all filters → top%d: %s",
        len(scored), max_tickers, top,
    )

    # Pad with anchors if fewer than 2 stocks survive all filters
    for anchor in ANCHOR_TICKERS:
        if anchor not in top:
            if len(top) < 2:
                top.append(anchor)
                logger.info("daily_premarket_scan: padded with anchor %s", anchor)

    # ── Pin user watchlist tickers — always include, front of list ────────────
    # These bypass the gap/RVOL filter. They are prepended so the bot evaluates
    # them every tick regardless of whether the dynamic scan picked them today.
    if _user_pins:
        pinned_new = [t for t in _user_pins if t not in top]
        top = _user_pins + [t for t in top if t not in _user_pins]
        # Respect max_tickers cap: trim from the tail (lowest-scoring dynamic names)
        top = top[:max(max_tickers, len(_user_pins))]
        if pinned_new:
            logger.info(
                "daily_premarket_scan: pinned %d user watchlist ticker(s) into result: %s",
                len(pinned_new), pinned_new,
            )

    # ── Persist results ───────────────────────────────────────────────────────
    _write_daily_universe(today_str, top, scored[:max_tickers])
    scores_dict = {s["ticker"]: s["score"] for s in scored}
    _write_state(top, scores_dict)

    return top


def get_watchlist() -> list[str]:
    """
    Read today's scanned watchlist from disk.

    Priority:
    1. daily_universe.json (from today's dynamic scan)
    2. scanner_state.json  (from the most recent rescore)
    3. ANCHOR_TICKERS      (fallback if nothing fresh exists)

    Stale check: the daily universe is valid for the entire trading day.
    The rescore cache expires after 2 hours to catch restart scenarios.
    """
    today_str = _et_now().strftime("%Y-%m-%d")

    # ── Try today's daily universe first ─────────────────────────────────────
    try:
        daily = _read_daily_universe()
        if daily.get("date") == today_str and daily.get("universe"):
            return list(daily["universe"])
    except Exception as ex:
        logger.debug("get_watchlist: daily_universe.json read error: %s", ex)

    # ── Fall back to scanner_state.json (rescore cache) ──────────────────────
    try:
        if not SCANNER_STATE.exists():
            return list(ANCHOR_TICKERS)
        data = json.loads(SCANNER_STATE.read_text())

        written_iso = data.get("written_utc", "")
        if written_iso:
            written_dt = datetime.fromisoformat(written_iso)
            age_hours  = (datetime.utcnow() - written_dt).total_seconds() / 3600
            if age_hours > 2.0:
                logger.debug("Scanner state stale (%.1fh) — using anchors", age_hours)
                return list(ANCHOR_TICKERS)

        wl = data.get("watchlist", [])
        return wl if wl else list(ANCHOR_TICKERS)

    except Exception as ex:
        logger.warning("get_watchlist: scanner_state.json read error: %s — using anchors", ex)
        return list(ANCHOR_TICKERS)


def get_today_universe() -> list[str]:
    """
    Return today's dynamic ticker universe (from daily_premarket_scan).
    Falls back to config.TICKER_UNIVERSE if today's scan hasn't run yet.
    Convenience alias used by dashboard and analyze_today_exits.
    """
    today_str = _et_now().strftime("%Y-%m-%d")
    try:
        daily = _read_daily_universe()
        if daily.get("date") == today_str and daily.get("universe"):
            return list(daily["universe"])
    except Exception:
        pass
    return list(TICKER_UNIVERSE)


def is_premarket_window() -> bool:
    """True during 09:00–09:29 ET."""
    et = _et_now()
    return _hm_in_range(et.hour, et.minute, PREMARKET_START_HM, PREMARKET_END_HM)


def is_scan_window() -> bool:
    """True during pre-market OR early session (09:00–11:30 ET)."""
    et = _et_now()
    return (
        _hm_in_range(et.hour, et.minute, PREMARKET_START_HM, PREMARKET_END_HM)
        or _hm_in_range(et.hour, et.minute, SESSION_START_HM, SESSION_END_HM)
    )


# ── Internal helpers ──────────────────────────────────────────────────────────

def _write_state(watchlist: list[str], scores: dict[str, float]) -> None:
    """Persist watchlist + scores to scanner_state.json for cross-process reads."""
    try:
        SCANNER_STATE.write_text(json.dumps({
            "written_utc": datetime.utcnow().isoformat(),
            "watchlist":   watchlist,
            "scores":      {t: round(s, 6) for t, s in scores.items() if s > 0},
        }, indent=2))
    except Exception as ex:
        logger.warning("Scanner state write failed: %s", ex)


def _write_daily_universe(
    date: str,
    universe: list[str],
    details: list[dict],
) -> None:
    """Write the day's scanned universe to daily_universe.json."""
    try:
        DAILY_UNIVERSE_PATH.write_text(json.dumps({
            "date":         date,
            "universe":     universe,
            "scan_details": details,
            "written_utc":  datetime.utcnow().isoformat(),
        }, indent=2))
    except Exception as ex:
        logger.warning("daily_universe.json write failed: %s", ex)


def _read_daily_universe() -> dict:
    """Read daily_universe.json; returns empty dict on any error."""
    try:
        if DAILY_UNIVERSE_PATH.exists():
            return json.loads(DAILY_UNIVERSE_PATH.read_text())
    except Exception as ex:
        logger.debug("_read_daily_universe: %s", ex)
    return {}
