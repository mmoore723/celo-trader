"""
dashboard/components/trade_plan.py — Daily trade plan generator and banner.
"""
import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path

from config import get_settings, STARTING_CAPITAL
from trading_logic import LIVE_STATE
from broker import get_clients
from dashboard.css import T

# DAILY TRADE PLAN — generated once at 09:15 ET, displayed as banner on Live page
# ═══════════════════════════════════════════════════════════════════════════════

def _generate_trade_plan(ticker: str) -> dict | None:
    """
    Pull yesterday's OHLC, the rolling 5-day weekly range, and today's
    pre-market bars (04:00–09:15 ET).  Returns a plain-English trade-plan
    dict or None if data is unavailable.

    Keys returned:
      ticker, yest_open, yest_high, yest_low, yest_close,
      week_high, week_low, pm_high, pm_low, pm_last,
      gap_type, gap_pct, inside_range, bias, bias_reason,
      key_levels, generated_at
    """
    import datetime as _dt2
    try:
        import pytz as _pytz2
        _ET = _pytz2.timezone("America/New_York")
        _now_et = _dt2.datetime.now(_ET)
    except ImportError:
        _tz_off = _dt2.timezone(_dt2.timedelta(hours=-4))
        _now_et = _dt2.datetime.utcnow().replace(tzinfo=_tz_off)

    try:
        from broker import AlpacaClient as _PlanAC
        _bkr = _PlanAC()
        if _bkr is None:
            return None

        # ── Yesterday's daily OHLC ────────────────────────────────────────────
        _daily_bars, _err = _bkr.get_bars(ticker, "1Day", limit=10)
        if _err or not _daily_bars:
            return None

        # Alpaca returns bars newest-last; sort by time just in case
        _daily_bars = sorted(_daily_bars, key=lambda b: b.get("t", ""))
        # Most recent COMPLETED session = last bar whose date < today
        _today_str = _now_et.date().isoformat()
        _prev_bars = [b for b in _daily_bars if str(b.get("t", ""))[:10] < _today_str]
        if not _prev_bars:
            return None
        _yest = _prev_bars[-1]
        yest_open  = float(_yest.get("o", 0) or 0)
        yest_high  = float(_yest.get("h", 0) or 0)
        yest_low   = float(_yest.get("l", 0) or 0)
        yest_close = float(_yest.get("c", 0) or 0)
        if yest_close <= 0:
            return None

        # ── Weekly high/low (last 5 trading sessions) ─────────────────────────
        _week_bars = _prev_bars[-5:]
        week_high = max(float(b.get("h", 0) or 0) for b in _week_bars)
        week_low  = min(float(b.get("l", 0) or 0) for b in _week_bars if float(b.get("l", 0) or 0) > 0)
        week_range = week_high - week_low

        # ── Pre-market bars (04:00–09:15 ET today) ───────────────────────────
        # Alpaca extended-hours bars endpoint
        try:
            _pm_start = _now_et.replace(hour=4, minute=0, second=0, microsecond=0)
            _pm_end   = _now_et.replace(hour=9, minute=15, second=0, microsecond=0)
            _pm_url   = f"{_bkr.data}/v2/stocks/{ticker}/bars"
            _pm_params = {
                "timeframe":  "5Min",
                "start":      _pm_start.isoformat(),
                "end":        _pm_end.isoformat(),
                "limit":      100,
                "adjustment": "split",
                "feed":       "sip",
            }
            _pm_resp = _bkr.session.get(_pm_url, params=_pm_params, timeout=8)
            _pm_data = _pm_resp.json() if _pm_resp.status_code == 200 else {}
            _pm_bars = _pm_data.get("bars", [])
        except Exception:
            _pm_bars = []

        pm_high = max((float(b.get("h", 0) or 0) for b in _pm_bars), default=0.0)
        pm_low  = min((float(b.get("l", 0) or 0) for b in _pm_bars if float(b.get("l", 0) or 0) > 0), default=0.0)
        pm_last = float(_pm_bars[-1].get("c", 0) or 0) if _pm_bars else 0.0

        # If no pre-market data (weekend / data not available), use yesterday close
        if pm_last <= 0:
            pm_last = yest_close
        if pm_high <= 0:
            pm_high = yest_close
        if pm_low  <= 0:
            pm_low  = yest_close

        # ── Gap analysis ──────────────────────────────────────────────────────
        gap_pct   = (pm_last - yest_close) / yest_close * 100
        if gap_pct > 0.30:
            gap_type = "Gap Up"
        elif gap_pct < -0.30:
            gap_type = "Gap Down"
        else:
            gap_type = "Flat Open"

        # Inside or outside yesterday's range?
        inside_range = (pm_last <= yest_high) and (pm_last >= yest_low)

        # ── Overnight high / low context ──────────────────────────────────────
        overnight_high = pm_high
        overnight_low  = pm_low

        # ── Primary bias logic ────────────────────────────────────────────────
        # Score: +1 for each bullish factor, -1 for each bearish factor
        _score = 0
        _reasons: list[str] = []

        # Factor 1 — Gap direction
        if gap_pct > 0.50:
            _score += 2
            _reasons.append(f"Price is gapping UP {gap_pct:+.2f}% above yesterday's close (strong buyer interest overnight)")
        elif gap_pct > 0.15:
            _score += 1
            _reasons.append(f"Small gap up {gap_pct:+.2f}% — slight edge to buyers at open")
        elif gap_pct < -0.50:
            _score -= 2
            _reasons.append(f"Price is gapping DOWN {gap_pct:+.2f}% below yesterday's close (sellers in control overnight)")
        elif gap_pct < -0.15:
            _score -= 1
            _reasons.append(f"Small gap down {gap_pct:+.2f}% — slight edge to sellers at open")
        else:
            _reasons.append(f"Opening near yesterday's close (flat gap of {gap_pct:+.2f}%) — no strong overnight move")

        # Factor 2 — Pre-market last price vs yesterday's midpoint
        yest_mid = (yest_high + yest_low) / 2
        if pm_last > yest_mid:
            _score += 1
            _reasons.append(f"Pre-market price (${pm_last:.2f}) is above yesterday's midpoint (${yest_mid:.2f}) — buyers holding the high half")
        elif pm_last < yest_mid:
            _score -= 1
            _reasons.append(f"Pre-market price (${pm_last:.2f}) is below yesterday's midpoint (${yest_mid:.2f}) — sellers pressing the low half")

        # Factor 3 — Opening inside vs outside yesterday's range
        if not inside_range and pm_last > yest_high:
            _score += 1
            _reasons.append(f"Price is already ABOVE yesterday's high (${yest_high:.2f}) — breakout territory, CALL bias")
        elif not inside_range and pm_last < yest_low:
            _score -= 1
            _reasons.append(f"Price is already BELOW yesterday's low (${yest_low:.2f}) — breakdown territory, PUT bias")
        else:
            _reasons.append(f"Price is INSIDE yesterday's range (${yest_low:.2f} – ${yest_high:.2f}) — ORB will decide direction")

        # Factor 4 — Weekly range position
        if week_range > 0:
            _wk_pos = (pm_last - week_low) / week_range  # 0=week low, 1=week high
            if _wk_pos > 0.75:
                _score += 1
                _reasons.append(f"Near the TOP of the week's range ({_wk_pos*100:.0f}% of week) — momentum is up for the week")
            elif _wk_pos < 0.25:
                _score -= 1
                _reasons.append(f"Near the BOTTOM of the week's range ({_wk_pos*100:.0f}% of week) — momentum is down for the week")
            else:
                _reasons.append(f"In the middle of the week's range ({_wk_pos*100:.0f}% of week) — no weekly bias edge")

        # ── Bias decision ─────────────────────────────────────────────────────
        if _score >= 2:
            bias = "BULLISH"
            bias_emoji = "🟢"
            bias_short = "Watching for CALL (buy) at 09:30 ORB breakout above OR High"
        elif _score <= -2:
            bias = "BEARISH"
            bias_emoji = "🔴"
            bias_short = "Watching for PUT (sell) at 09:30 ORB breakdown below OR Low"
        else:
            bias = "NEUTRAL"
            bias_emoji = "⚪"
            bias_short = "Mixed signals — let the 09:30 ORB candle decide the direction, do not pre-bias"

        # ── Key levels ────────────────────────────────────────────────────────
        key_levels = {
            "Yesterday High":    f"${yest_high:.2f}  ← price above this = clear CALL territory",
            "Yesterday Low":     f"${yest_low:.2f}  ← price below this = clear PUT territory",
            "Yesterday Close":   f"${yest_close:.2f}  ← overnight reference price",
            "Pre-Market High":   f"${pm_high:.2f}  ← overnight buyers topped out here",
            "Pre-Market Low":    f"${pm_low:.2f}  ← overnight sellers bottomed here",
            "Week High":         f"${week_high:.2f}  ← 5-day ceiling",
            "Week Low":          f"${week_low:.2f}  ← 5-day floor",
        }

        return {
            "ticker":        ticker,
            "yest_open":     yest_open,
            "yest_high":     yest_high,
            "yest_low":      yest_low,
            "yest_close":    yest_close,
            "week_high":     week_high,
            "week_low":      week_low,
            "pm_high":       pm_high,
            "pm_low":        pm_low,
            "pm_last":       pm_last,
            "gap_type":      gap_type,
            "gap_pct":       gap_pct,
            "inside_range":  inside_range,
            "bias":          bias,
            "bias_emoji":    bias_emoji,
            "bias_short":    bias_short,
            "reasons":       _reasons,
            "key_levels":    key_levels,
            "score":         _score,
            "generated_at":  _now_et.strftime("%I:%M %p ET"),
        }

    except Exception as _e:
        import logging as _tp_log
        _tp_log.getLogger("celo_trader.dashboard").warning(
            "Daily trade plan generation failed: %s", _e
        )
        return None


def _render_trade_plan_banner(plan: dict) -> None:
    """
    Render the Daily Trade Plan as a Bloomberg/CNN-style financial brief.
    Premium newsletter aesthetic: dark masthead, structured data panels,
    clean sans-serif typography, muted color palette with signal accents.
    """
    if plan is None:
        return

    bias     = plan["bias"]
    ticker   = plan["ticker"]
    gap_pct  = plan["gap_pct"]
    score    = plan["score"]

    # ── Color tokens by bias ──────────────────────────────────────────────────
    if bias == "BULLISH":
        _accent   = "#16a34a"   # green
        _accent_l = "#dcfce7"
        _accent_t = "#14532d"
        _badge_bg = "#16a34a"
        _badge_tx = "#ffffff"
        _signal   = "CALL"
        _action   = f"Watch for breakout ABOVE ${plan['yest_high']:.2f} on elevated volume."
        _action_d = (
            f"If the first 5-min candle closes above OR High with ≥2× volume, "
            f"bot enters a CALL. Weak open (small body, thin volume) = stand aside."
        )
    elif bias == "BEARISH":
        _accent   = "#dc2626"
        _accent_l = "#fee2e2"
        _accent_t = "#7f1d1d"
        _badge_bg = "#dc2626"
        _badge_tx = "#ffffff"
        _signal   = "PUT"
        _action   = f"Watch for breakdown BELOW ${plan['yest_low']:.2f} on elevated volume."
        _action_d = (
            f"If the first 5-min candle closes below OR Low with ≥2× volume, "
            f"bot enters a PUT. Strong bounce off the low = wait for confirmation."
        )
    else:
        _accent   = "#d97706"
        _accent_l = "#fef3c7"
        _accent_t = "#78350f"
        _badge_bg = "#d97706"
        _badge_tx = "#ffffff"
        _signal   = "WAIT"
        _action   = f"No directional lean. Range: ${plan['yest_low']:.2f} – ${plan['yest_high']:.2f}."
        _action_d = (
            "Mixed signals — let the ORB candle define direction before committing. "
            "Bot trades whichever side breaks with volume ≥200% normal."
        )

    _gap_sign  = "▲" if gap_pct >= 0 else "▼"
    _gap_color = "#16a34a" if gap_pct >= 0 else "#dc2626"

    # ── Score bar ─────────────────────────────────────────────────────────────
    _meter_pct   = max(0, min(100, int((score + 4) / 8 * 100)))
    _meter_color = "#16a34a" if score >= 2 else "#dc2626" if score <= -2 else "#d97706"

    # ── Inside / outside range note ───────────────────────────────────────────
    _range_note = (
        "Inside yesterday's range — ORB will decide direction."
        if plan["inside_range"] else
        (f"Above yesterday's high (${plan['yest_high']:.2f}) — buyers in control pre-bell."
         if plan["pm_last"] > plan["yest_high"] else
         f"Below yesterday's low (${plan['yest_low']:.2f}) — sellers in control pre-bell.")
    )

    # ── Reasons as numbered list items ────────────────────────────────────────
    _reason_items = "".join(
        f'<div style="display:flex;gap:10px;padding:6px 0;'
        f'border-bottom:1px solid #f3f4f6">'
        f'<span style="font-size:.72rem;font-weight:700;color:{_accent};'
        f'min-width:18px;padding-top:1px">{i}.</span>'
        f'<span style="font-size:.78rem;color:#374151;line-height:1.5">{r}</span>'
        f'</div>'
        for i, r in enumerate(plan["reasons"], 1)
    )

    # ── Key levels rows ───────────────────────────────────────────────────────
    _level_rows = "".join(
        f'<tr>'
        f'<td style="padding:5px 12px;font-size:.74rem;font-weight:600;'
        f'color:#374151;white-space:nowrap;border-bottom:1px solid #f3f4f6">{k}</td>'
        f'<td style="padding:5px 12px;font-size:.74rem;color:#6b7280;'
        f'border-bottom:1px solid #f3f4f6">{v}</td>'
        f'</tr>'
        for k, v in plan["key_levels"].items()
    )

    # ── Shared inline style strings (no CSS classes — Streamlit drops <style>) ──
    _F  = "font-family:-apple-system,'Helvetica Neue',Arial,sans-serif"
    _S0 = f"{_F};border-radius:6px;overflow:hidden;border:1px solid #e5e7eb;margin-bottom:10px;box-shadow:0 2px 8px rgba(0,0,0,.08)"
    # masthead
    _S1 = "background:#111827;padding:10px 18px;display:flex;align-items:center;gap:10px;flex-wrap:wrap"
    _S_pub  = "font-size:.60rem;font-weight:800;letter-spacing:.18em;text-transform:uppercase;color:#9ca3af"
    _S_div  = "color:#4b5563;font-size:.85rem"
    _S_ts   = "font-size:.68rem;color:#6b7280;letter-spacing:.04em"
    _S_badge= f"background:{_badge_bg};color:{_badge_tx};font-size:.60rem;font-weight:800;letter-spacing:.12em;text-transform:uppercase;padding:3px 10px;border-radius:3px;margin-left:auto"
    # headline
    _S2     = f"background:#1f2937;padding:12px 18px 10px;border-bottom:3px solid {_accent}"
    _S_hll  = f"font-size:.60rem;font-weight:700;letter-spacing:.14em;text-transform:uppercase;color:{_accent};margin-bottom:4px"
    _S_hlt  = "font-size:1.0rem;font-weight:700;color:#f9fafb;line-height:1.3"
    _S_hls  = "font-size:.72rem;color:#9ca3af;margin-top:4px"
    # kpi row
    _S3     = "display:grid;grid-template-columns:repeat(4,1fr);border-bottom:1px solid #e5e7eb;background:#fff"
    _S_kpi  = "padding:10px 14px;border-right:1px solid #f3f4f6"
    _S_kpil = "font-size:.58rem;font-weight:700;letter-spacing:.10em;text-transform:uppercase;color:#9ca3af;margin-bottom:3px"
    _S_kpiv = "font-size:.90rem;font-weight:700;color:#111827"
    # section
    _S_sec  = "padding:12px 18px;border-bottom:1px solid #f3f4f6;background:#fff"
    _S_secl = "font-size:.58rem;font-weight:800;letter-spacing:.14em;text-transform:uppercase;color:#9ca3af;margin-bottom:8px;padding-bottom:5px;border-bottom:1px solid #f3f4f6"
    # signal box
    _S_sig  = f"background:{_accent_l};border-left:4px solid {_accent};border-radius:0 4px 4px 0;padding:10px 14px;margin-top:6px"
    _S_sigh = f"font-size:.70rem;font-weight:800;letter-spacing:.08em;text-transform:uppercase;color:{_accent_t};margin-bottom:3px"
    _S_sigb = "font-size:.76rem;color:#374151;line-height:1.5"
    # reason row
    _S_rrow = "display:flex;gap:10px;padding:6px 0;border-bottom:1px solid #f3f4f6"
    _S_rnum = f"font-size:.72rem;font-weight:700;color:{_accent};min-width:18px;padding-top:1px"
    _S_rtxt = "font-size:.76rem;color:#374151;line-height:1.5"
    # meter
    _S_mlbl = "display:flex;justify-content:space-between;font-size:.58rem;color:#9ca3af;margin-bottom:4px"
    _S_mtrk = "background:#e5e7eb;border-radius:2px;height:6px;overflow:hidden"
    _S_mfil = f"width:{_meter_pct}%;height:100%;background:{_meter_color};border-radius:2px"
    _S_mscr = f"font-size:.66rem;font-weight:700;color:{_meter_color};margin-top:4px;text-align:right"

    # ── Build reason items with inline styles ─────────────────────────────────
    _reason_items = "".join(
        f'<div style="{_S_rrow}">'
        f'<span style="{_S_rnum}">{i}.</span>'
        f'<span style="{_S_rtxt}">{r}</span>'
        f'</div>'
        for i, r in enumerate(plan["reasons"], 1)
    )

    # ── Build key levels rows with inline styles ──────────────────────────────
    _S_td1 = "padding:5px 12px;font-size:.74rem;font-weight:600;color:#374151;white-space:nowrap;border-bottom:1px solid #f3f4f6"
    _S_td2 = "padding:5px 12px;font-size:.74rem;color:#6b7280;border-bottom:1px solid #f3f4f6"
    _level_rows = "".join(
        f'<tr><td style="{_S_td1}">{k}</td><td style="{_S_td2}">{v}</td></tr>'
        for k, v in plan["key_levels"].items()
    )

    st.markdown(
        f'<div style="{_S0}">'

        # MASTHEAD
        f'<div style="{_S1}">'
        f'<span style="{_S_pub}">Celo Trader</span>'
        f'<span style="{_S_div}">|</span>'
        f'<span style="{_S_pub};letter-spacing:.06em;font-weight:400">Market Intelligence</span>'
        f'<span style="{_S_div}">|</span>'
        f'<span style="{_S_ts}">{plan["generated_at"]} ET</span>'
        f'<span style="{_S_badge}">{_signal} SIGNAL</span>'
        f'</div>'

        # HEADLINE
        f'<div style="{_S2}">'
        f'<div style="{_S_hll}">{ticker} &middot; Daily Trade Brief</div>'
        f'<div style="{_S_hlt}">{plan["bias_short"]}</div>'
        f'<div style="{_S_hls}">{_range_note}</div>'
        f'</div>'

        # KPI ROW
        f'<div style="{_S3}">'
        f'<div style="{_S_kpi}"><div style="{_S_kpil}">Pre-Market</div><div style="{_S_kpiv}">${plan["pm_last"]:.2f}</div></div>'
        f'<div style="{_S_kpi}"><div style="{_S_kpil}">Gap</div><div style="{_S_kpiv};color:{_gap_color}">{_gap_sign} {abs(gap_pct):.2f}%</div></div>'
        f'<div style="{_S_kpi}"><div style="{_S_kpil}">Prev Close</div><div style="{_S_kpiv}">${plan["yest_close"]:.2f}</div></div>'
        f'<div style="{_S_kpi};border-right:none"><div style="{_S_kpil}">Week Range</div><div style="{_S_kpiv};font-size:.78rem">${plan["week_low"]:.2f} &ndash; ${plan["week_high"]:.2f}</div></div>'
        f'</div>'

        # SIGNAL
        f'<div style="{_S_sec}">'
        f'<div style="{_S_secl}">09:30 Open Strategy</div>'
        f'<div style="{_S_sig}">'
        f'<div style="{_S_sigh}">{_signal} Setup</div>'
        f'<div style="{_S_sigb}"><strong>{_action}</strong><br>{_action_d}</div>'
        f'</div></div>'

        # ANALYSIS
        f'<div style="{_S_sec}">'
        f'<div style="{_S_secl}">Signal Analysis &mdash; {score:+d} / 4 factors {bias}</div>'
        f'{_reason_items}'
        f'<div style="margin-top:10px">'
        f'<div style="{_S_mlbl}"><span>Very Bearish</span><span>Neutral</span><span>Very Bullish</span></div>'
        f'<div style="{_S_mtrk}"><div style="{_S_mfil}"></div></div>'
        f'<div style="{_S_mscr}">Conviction: {score:+d}/4 &rarr; {bias}</div>'
        f'</div></div>'

        # KEY LEVELS
        f'<div style="{_S_sec};border-bottom:none">'
        f'<div style="{_S_secl}">Key Price Levels</div>'
        f'<table style="width:100%;border-collapse:collapse">{_level_rows}</table>'
        f'</div>'

        f'</div>',
        unsafe_allow_html=True,
    )

    # ── Dismiss ───────────────────────────────────────────────────────────────
    if st.button("Dismiss brief", key="tp_dismiss", type="secondary"):
        st.session_state["trade_plan_dismissed"] = True
        st.rerun()


