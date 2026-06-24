"""
dashboard/components/price_bar.py — Scrolling price ticker pinned to viewport bottom.
"""
import streamlit as st
from broker import get_clients
from dashboard.css import T

# ── Live price ticker bar ─────────────────────────────────────────────────────
# Defined here (module level) so it can be called once AFTER all page branches.
# position:fixed CSS keeps it pinned to the bottom of the viewport on every page.

_TICKER_SYMBOLS = ["SPY", "QQQ", "AAPL", "NVDA", "TSLA", "AMC"]

@st.fragment(run_every=60)
def _price_ticker_bar():
    """
    Scrolling price bar pinned to the bottom of the viewport.
    Refreshes every 60 s via @st.fragment — one API call per refresh
    using get_snapshots() instead of 12 individual quote+bar calls.
    Falls back to session_state cache if the API is rate-limited.
    """
    _alpaca_tb, _ = get_clients()
    _items: list[str] = []

    # ONE batch call for all symbols — avoids hitting the free-tier 429 limit
    _snaps = _alpaca_tb.get_snapshots(_TICKER_SYMBOLS)

    # Merge live data into session_state cache; display cached data on failure
    for _sym in _TICKER_SYMBOLS:
        _snap = _snaps.get(_sym)
        if _snap and _snap.get("price", 0) > 0:
            # Live data available — update cache
            _px      = _snap["price"]
            _chg_pct = _snap["change_pct"]
            st.session_state[f"_tb_px_{_sym}"]  = _px
            st.session_state[f"_tb_chg_{_sym}"] = _chg_pct
        else:
            # Rate-limited or error — silently use last known values
            _px      = st.session_state.get(f"_tb_px_{_sym}", 0.0)
            _chg_pct = st.session_state.get(f"_tb_chg_{_sym}", 0.0)

        _arrow  = "▲" if _chg_pct >= 0 else "▼"
        _cls    = "ticker-up" if _chg_pct >= 0 else "ticker-dn"
        _sign   = "+" if _chg_pct >= 0 else ""
        _px_str  = f"${_px:.2f}" if _px else "—"
        _chg_str = f"{_sign}{_chg_pct:.2f}%" if _px else ""

        _items.append(
            f'<span class="ticker-item">'
            f'<span class="ticker-sym">{_sym}</span>'
            f'<span class="ticker-px">&nbsp;{_px_str}</span>'
            f'<span class="{_cls}">&nbsp;{_arrow} {_chg_str}</span>'
            f'</span>'
        )

    _inner = "".join(_items)
    st.markdown(
        f'<div class="ticker-wrap"><div class="ticker-track">'
        f'{_inner}{_inner}'   # duplicate for seamless infinite loop
        f'</div></div>',
        unsafe_allow_html=True,
    )


