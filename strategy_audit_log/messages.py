"""
strategy_audit_log/messages.py — plain-English message builders for each of
the 4 narration sections in audit_plain_english().

Split out of the old single strategy_audit_log.py (2026-08-01, file-size
cleanup). Each function takes the specific values it needs as explicit
params rather than sharing audit.py's local scope — pure string-formatting
helpers, no logic changed from the original inline blocks.
"""
from __future__ import annotations

from strategy_audit_log.constants import _STRAT_NAMES


def build_structure_message(
    ticker: str, bar_str: str, trend: str,
    highs: list, lows: list,
    last_sh: float | None, last_sl: float | None,
    close_now: float, vwap_now: float,
) -> str:
    """Structural-change narration (section 1 of audit_plain_english)."""
    if trend == "downtrend":
        is_lh = len(highs) >= 2 and highs[-1]["price"] < highs[-2]["price"]
        is_ll = len(lows)  >= 2 and lows[-1]["price"]  < lows[-2]["price"]
        if is_lh and is_ll:
            return (
                f"{ticker} {bar_str} — Bearish structure confirmed. "
                f"Lower High ${last_sh:.2f} + Lower Low ${last_sl:.2f}. "
                f"Bot looking for SHORT/PUT entries."
            )
        elif is_lh:
            return (
                f"{ticker} {bar_str} — Lower High at ${last_sh:.2f}. "
                f"Rally failed below prior peak — sellers in control. Waiting for LL confirmation."
            )
        else:
            return (
                f"{ticker} {bar_str} — Downtrend in progress. "
                f"Last SH ${last_sh:.2f}, last SL ${last_sl:.2f}. "
                f"Price ${close_now:.2f} {'below' if close_now < vwap_now else 'above'} VWAP."
            )
    elif trend == "uptrend":
        is_hh = len(highs) >= 2 and highs[-1]["price"] > highs[-2]["price"]
        is_hl = len(lows)  >= 2 and lows[-1]["price"]  > lows[-2]["price"]
        if is_hh and is_hl:
            return (
                f"{ticker} {bar_str} — Bullish structure confirmed. "
                f"Higher High ${last_sh:.2f} + Higher Low ${last_sl:.2f}. "
                f"Bot looking for LONG/CALL entries."
            )
        elif is_hl:
            return (
                f"{ticker} {bar_str} — Higher Low at ${last_sl:.2f}. "
                f"Pullback held above prior low — buyers defending. Waiting for HH."
            )
        else:
            return (
                f"{ticker} {bar_str} — Uptrend in progress. "
                f"Last SH ${last_sh:.2f}, last SL ${last_sl:.2f}."
            )
    else:
        return (
            f"{ticker} {bar_str} — Consolidating. No clear trend. "
            f"Bot waiting for breakout."
        )


def build_rvol_message(ticker: str, bar_str: str, rvol_now: float) -> tuple[str, str]:
    """
    RVOL-tier advisory (section 2 of audit_plain_english).
    Returns (cur_rvol_tier, rvol_msg) — the tier is returned so the caller
    can dedup against _last_audit_state["rvol_tier"] before logging.
    """
    cur_rvol_tier = ("≥2.0" if rvol_now >= 2.0 else "≥1.5" if rvol_now >= 1.5
                      else "≥1.2" if rvol_now >= 1.2 else "<1.2")
    if rvol_now >= 2.0:
        rvol_msg = f"{ticker} {bar_str} — Volume {rvol_now:.1f}× average. All strategies eligible."
    elif rvol_now >= 1.5:
        rvol_msg = (
            f"{ticker} {bar_str} — Volume {rvol_now:.1f}×. "
            f"BOS/VWAP/FVG eligible. ORB needs 2.0×."
        )
    elif rvol_now >= 1.2:
        rvol_msg = (
            f"{ticker} {bar_str} — Volume {rvol_now:.1f}×. "
            f"Only TREND_CONT + CHAN_BREAK eligible. Waiting for volume."
        )
    else:
        rvol_msg = (
            f"{ticker} {bar_str} — Volume low ({rvol_now:.1f}×). "
            f"No strategies eligible. Watching."
        )
    return cur_rvol_tier, rvol_msg


def build_entry_message(ticker: str, bar_str: str, close_now: float, top) -> str:
    """Signal-fired narration (section 3 of audit_plain_english)."""
    name    = _STRAT_NAMES.get(top.strategy_id, top.strategy_id)
    dir_txt = "PUT (short)" if top.direction == "bearish" else "CALL (long)"
    meta    = top.meta or {}

    if top.strategy_id == "INST_ORB":
        flipped = meta.get("direction_flipped", False)
        return (
            f"{ticker} {bar_str} — ENTRY: {name}{'  [failed-breakout fade]' if flipped else ''}. "
            f"Price broke {'above' if top.direction == 'bullish' else 'below'} the opening range "
            f"with {top.rvol:.1f}× volume. Entering {dir_txt}."
        )
    elif top.strategy_id == "BOS_MSS":
        return (
            f"{ticker} {bar_str} — ENTRY: {name}. "
            f"Broke prior swing {'high' if top.direction == 'bullish' else 'low'}. "
            f"Volume {top.rvol:.1f}×. Entering {dir_txt}."
        )
    elif top.strategy_id == "TREND_CONT":
        lh_p = meta.get("lh_price") or meta.get("hl_price", close_now)
        return (
            f"{ticker} {bar_str} — ENTRY: {name} (re-entry). "
            f"{'LH' if top.direction == 'bearish' else 'HL'} at ${lh_p:.2f} — "
            f"trend resuming. Volume {top.rvol:.1f}×. Entering {dir_txt}."
        )
    elif top.strategy_id == "CHAN_BREAK":
        proj = meta.get("projected", close_now)
        return (
            f"{ticker} {bar_str} — ENTRY: {name}. "
            f"Trendline tag at ~${proj:.2f}, rejection confirmed. "
            f"Volume {top.rvol:.1f}×. Entering {dir_txt}."
        )
    else:
        return (
            f"{ticker} {bar_str} — ENTRY: {name} {dir_txt}. "
            f"Volume {top.rvol:.1f}×, conf {top.confidence:.0%}."
        )


def build_skip_message(
    ticker: str, bar_str: str, rvol_now: float, trend: str,
    close_now: float, vwap_now: float,
) -> str:
    """No-signal / blocking-reason narration (section 4 of audit_plain_english)."""
    if rvol_now < 1.2:
        return (
            f"{ticker} {bar_str} — No entry. Volume {rvol_now:.1f}× "
            f"(need ≥1.2× for any strategy). Watching."
        )
    elif trend == "consolidation":
        return (
            f"{ticker} {bar_str} — No entry. Ranging — no confirmed trend. "
            f"Bot waiting for breakout."
        )
    else:
        vwap_side = "above" if close_now > vwap_now else "below"
        return (
            f"{ticker} {bar_str} — Trend: {trend}. "
            f"Price ${close_now:.2f} ({vwap_side} VWAP). "
            f"Volume {rvol_now:.1f}×. No pattern triggered — monitoring."
        )
