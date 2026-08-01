"""
scanner/constants.py — Ticker universe, blacklist, ETF set, timing
windows, and scan thresholds shared across the scanner package.

Split out of the old single scanner.py (2026-08-01, file-size cleanup); no
logic changed, only relocated.
"""

from config import TICKER_UNIVERSE, BASE_DIR

SCANNER_STATE       = BASE_DIR / "scanner_state.json"
DAILY_UNIVERSE_PATH = BASE_DIR / "daily_universe.json"

# ── ETF set — liquidity bonus in scoring ──────────────────────────────────────
_ETF_SET = {"SPY", "QQQ", "IWM", "DIA", "XLE", "GLD",
            "XLK", "XLF", "XLV", "XLY", "XLI", "XLB", "XLC",
            "SMH"}   # VanEck Semiconductor ETF — deep options, high gap freq

# ── Hard blacklist — leveraged/inverse ETFs, VIX products ────────────────────
# TSLT (2× TSLA), TSLL (1.5× TSLA), NVDL (2× NVDA) etc. are explicitly
# blocked — leveraged ETFs inflate RVOL scores artificially.
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
# Names that structurally can't gap 1-4% are excluded from the scan.
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
_MIN_RVOL          = 2.0         # early-session RVOL vs normalized avg (individual stocks)
_MIN_RVOL_ETF      = 1.5         # ETFs move less; 1.5× is meaningful institutional signal
_MIN_GAP_PCT_ETF   = 0.5         # 0.5% gap on SPY/QQQ is a real directional move (not noise)
_MIN_ATR_DOLLARS   = 1.0         # ATR(14) on daily bars must be > $1

# Legacy intra-session ATR thresholds (used by _score_ticker rescore)
_ATR_MIN_DOLLARS = 1.50
_ATR_MIN_PCT     = 0.015


