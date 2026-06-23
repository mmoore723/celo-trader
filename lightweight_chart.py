"""
lightweight_chart.py — Renders Playbook strategy examples using TradingView's
own open-source charting library (Lightweight Charts, Apache-2.0 licensed)
instead of hand-rolled Plotly subplots.

Why this exists (2026-06-20 audit)
───────────────────────────────────
The user's direct feedback: "those charts look like child's play" next to
TradingView. Rebuilding TradingView's actual decade of charting engineering
from scratch in Plotly is a losing trade — the better move is to embed the
real thing. Lightweight Charts is the open-source library TradingView itself
publishes; embedding it gets professional candlestick rendering, smooth
zoom/pan, and clean typography for free, with our own annotations layered
on top.

This renders inside Streamlit via st.iframe — no extra Python dependency,
just a CDN script tag, so it stays consistent with this repo's "free APIs /
no paid services" constraint (CLAUDE.md rule 2).

Replay / step-through (closes the "static, not dynamic" gap)
───────────────────────────────────────────────────────────────
render_strategy_chart() accepts `reveal_count`. When set, only the first N
bars are drawn — pair this with a Streamlit slider/button in the caller
(dashboard.py) to let the user step through the setup candle by candle
instead of seeing a finished picture immediately. See dashboard.py's
Playbooks tabs for the slider wiring.

FIX 2026-06-20 (critical render bug): candles were rendering as a tiny sliver
crushed against the right edge with most of the chart blank. Root cause was
NOT the data (verified clean, uniform 5-min bars, single session) — it was a
classic Lightweight-Charts-in-an-iframe race: `container.clientWidth` was
read at `createChart()` time, before the iframe had been laid out by the
browser, so it could read 0 (or near-0). `fitContent()` then computed a
degenerate near-zero bar spacing to fit all bars into that ~0px width. When
the ResizeObserver fired afterward with the REAL width, `applyOptions({width})`
correctly grew the canvas — but Lightweight Charts does NOT auto-refit the
visible range on a resize; it preserves the existing (degenerate) bar
spacing and right-edge anchor. Result: the chart canvas got wide, but the
already-tiny-spaced candles stayed tiny and pinned to the right, with empty
canvas filling the rest. Fix: explicitly re-run `fitContent()` every time the
ResizeObserver reports a real width, plus two short setTimeout safety re-fits
to absorb any remaining layout timing race.
"""

import json

import pandas as pd
import streamlit as st

# Lightweight Charts v4 — pinned version so a CDN update can't silently change
# rendering behavior underneath the Playbooks page.
_LWC_CDN = "https://unpkg.com/lightweight-charts@4.1.3/dist/lightweight-charts.standalone.production.js"

_OUTCOME_COLORS = {
    "clean_win": "#22c55e",   # green
    "reversed":  "#ef4444",   # red
    "chopped":   "#9ca3af",   # gray
}

_OUTCOME_LABEL = {
    "clean_win": "Real outcome: favorable move followed",
    "reversed":  "Real outcome: price reversed against the signal",
    "chopped":   "Real outcome: chopped — no clean follow-through",
}

_OUTCOME_BADGE_TEXT = {
    "clean_win": "WORKED",
    "reversed":  "REVERSED",
    "chopped":   "CHOPPED",
}


def render_strategy_chart(
    bars: list[dict],
    signal_idx: int,
    entry_idx: int,
    exit_idx: int,
    outcome: str,
    ticker: str,
    date_str: str,
    direction: str,
    reveal_count: int | None = None,
    height: int = 460,
    vwap: list[float | None] | None = None,
    or_high: float | None = None,
    or_low: float | None = None,
    swing_points: list[dict] | None = None,
    signal_note: str | None = None,
    entry_note: str | None = None,
    exit_note: str | None = None,
) -> None:
    """
    Render one real historical example using Lightweight Charts.

    bars: list of {time, open, high, low, close, volume} dicts — REAL data
          from playbook_examples.json, never fabricated. time must be a
          string parseable as a pandas/JS Date (ISO-ish is fine).
    signal_idx / entry_idx / exit_idx: indices into `bars` for marker placement.
    outcome: "clean_win" | "reversed" | "chopped" — drives marker color + caption.
    reveal_count: if set, only render the first N bars (replay/step-through).
                  None or >= len(bars) renders the full example.

    Structural overlays (2026-06-20 — "stop leaving the reader to take the
    rules on faith"). All optional / backward-compatible: older cached
    examples that predate these fields simply omit the corresponding line.
    vwap:         per-bar VWAP values aligned 1:1 with `bars` (None entries
                  skipped) — drawn as a line so "VWAP Gate" in the rules
                  table becomes something you can actually see respected.
    or_high/low:  the day's Opening Range — drawn as flat dashed reference
                  lines for INST_ORB / MID_BRK, the only two strategies that
                  use it.
    swing_points: [{idx, price, type:"high"|"low"}] — real SH/SL pivots
                  detected inside the visible window, drawn as small
                  triangle markers so structure-dependent strategies
                  (BOS_MSS, AFT_REV, TREND_CONT, CHAN_BREAK) show the actual
                  swing points their rule is reacting to.

    On-chart callouts (2026-06-20 — direct user feedback: "I need this ON
    the chart not on the side of it" / "it needs to be dynamic not static")
    signal_note / entry_note / exit_note are short, plain-language strings
    shown via a single floating tooltip driven by the chart's own crosshair
    (hover or tap the ①②③ marker's candle to see why) — not a separate side
    panel, and not a static strip. See the inline comment above the
    `callouts` list for why a single crosshair-driven tooltip replaced an
    earlier always-visible-bubbles attempt (it collided with itself: the
    bot's entry rule guarantees signal+entry are exactly one candle apart,
    leaving no room for two permanently-visible boxes side by side). None
    of the three is required — omit any one and hovering its candle simply
    shows nothing.
    """
    if not bars:
        st.warning("No real example available for this strategy yet.")
        return

    n = len(bars) if reveal_count is None else max(1, min(reveal_count, len(bars)))
    visible = bars[:n]

    # Lightweight Charts wants UNIX seconds for intraday data, not date strings,
    # so candles render with correct minute-level spacing instead of collapsing
    # to one bar per day.
    candle_data, volume_data = [], []
    for b in visible:
        t = int(pd.Timestamp(b["time"]).timestamp())
        candle_data.append({
            "time": t, "open": b["open"], "high": b["high"],
            "low": b["low"], "close": b["close"],
        })
        vol_color = "rgba(34,197,94,0.5)" if b["close"] >= b["open"] else "rgba(239,68,68,0.5)"
        volume_data.append({"time": t, "value": b["volume"], "color": vol_color})

    # ── Real trade math for the marker labels + banner — computed from the
    # actual stored closes, not invented numbers. Only meaningful once both
    # the entry and exit bars are actually visible (reveal_count may hide
    # the exit while stepping through).
    direction_label = "CALL (bullish)" if direction == "bullish" else "PUT (bearish)"
    sign = 1 if direction == "bullish" else -1
    pct_move = None
    if entry_idx < n and exit_idx < n:
        entry_close = visible[entry_idx]["close"]
        exit_close = visible[exit_idx]["close"]
        pct_move = (exit_close - entry_close) / entry_close * sign * 100

    markers = []
    if signal_idx < n:
        markers.append({
            "time": candle_data[signal_idx]["time"],
            "position": "aboveBar", "color": "#f59e0b", "shape": "circle",
            "text": "① SIGNAL",
        })
    if entry_idx < n:
        markers.append({
            "time": candle_data[entry_idx]["time"],
            "position": "belowBar", "color": "#3b82f6", "shape": "arrowUp",
            "text": f"② ENTRY · {direction_label.split(' ')[0]}",
        })
    if exit_idx < n:
        exit_color = _OUTCOME_COLORS.get(outcome, "#9ca3af")
        exit_label = f"③ EXIT · {pct_move:+.2f}%" if pct_move is not None else "③ EXIT"
        markers.append({
            "time": candle_data[exit_idx]["time"],
            "position": "aboveBar", "color": exit_color, "shape": "arrowDown",
            "text": exit_label,
        })

    # ── Swing-point pivots (SH/SL) — small triangle markers distinct from
    # the signal/entry/exit markers above, so structure annotations don't
    # get confused with the trade-action markers.
    # FIX 2026-06-20 (two issues):
    # 1. Color darkened from #a78bfa (violet-400) to #7c3aed (violet-600) —
    #    the light theme needs real contrast against white.
    # 2. A real example showed a swing-low marker sitting right after entry,
    #    which reads as "the structure that caused this call" even though
    #    that low didn't exist yet at decision time — it formed afterward.
    #    Swings with before_signal=False (or missing, for older cached
    #    examples) are now suffixed "(after)" and rendered hollow/muted so
    #    they're legible as "this is what happened next," not "this is why."
    for sp in (swing_points or []):
        if sp["idx"] >= n:
            continue
        is_high = sp["type"] == "high"
        is_before = sp.get("before_signal", True)   # default True for old cache entries
        label = ("SH" if is_high else "SL") + ("" if is_before else " (after)")
        markers.append({
            "time": candle_data[sp["idx"]]["time"],
            "position": "aboveBar" if is_high else "belowBar",
            "color": "#7c3aed" if is_before else "#c4b5fd",
            "shape": "arrowDown" if is_high else "arrowUp",
            "text": label,
            "size": 0.6 if is_before else 0.45,
        })
    markers.sort(key=lambda m: m["time"])

    # ── On-chart callouts — plain-language notes attached directly to the
    # chart, not a side panel or a strip below it.
    # FIX 2026-06-20 (second pass): the first version floated these as
    # always-visible, absolutely-positioned bubbles anchored to each
    # candle's TIME coordinate. Direct user feedback (with a screenshot)
    # showed the real failure: signal and entry are ALWAYS exactly one
    # candle apart (the bot's entry rule — it never acts on the signal bar
    # itself), so two ~200px-wide always-visible boxes had nowhere to go
    # without colliding with each other and with the OR lines / VWAP /
    # swing markers underneath. A static strip below the chart fixed the
    # collision but moved the explanation OFF the chart, which is the one
    # thing that was explicitly asked for.
    # FIX: a SINGLE floating tooltip, driven by the chart's own crosshair
    # (subscribeCrosshairMove), shown only for whichever candle the cursor
    # is currently over. With Magnet crosshair mode already on (see
    # `crosshair: {{mode: 1}}` below), the reported time snaps exactly to
    # one candle at a time — so this is mutually exclusive by construction:
    # exactly zero or one callout is ever visible, which makes overlap
    # structurally impossible instead of something to avoid by careful
    # layout. It's genuinely dynamic (follows the cursor, tracks pan/zoom)
    # and lives directly over the candle it explains, the way TradingView's
    # own hover tooltips work — not a permanent fixture competing with the
    # candles/lines for space.
    callouts = []
    if signal_note and signal_idx < n:
        callouts.append({"time": candle_data[signal_idx]["time"], "color": "#f59e0b",
                          "tag": "① WHY THE BOT LOOKED HERE", "text": signal_note})
    if entry_note and entry_idx < n:
        callouts.append({"time": candle_data[entry_idx]["time"], "color": "#3b82f6",
                          "tag": "② WHY IT ENTERED HERE", "text": entry_note})
    if exit_note and exit_idx < n:
        callouts.append({
            "time": candle_data[exit_idx]["time"], "color": _OUTCOME_COLORS.get(outcome, "#9ca3af"),
            "tag": "③ WHY IT EXITED HERE", "text": exit_note,
        })

    # ── VWAP line — aligned 1:1 with visible bars, None values skipped so
    # Lightweight Charts just leaves a gap rather than plotting a fake zero.
    vwap_data = []
    if vwap:
        for b, v in zip(visible, vwap[:n]):
            if v is not None:
                vwap_data.append({"time": int(pd.Timestamp(b["time"]).timestamp()), "value": v})

    chart_id = f"lwc_{ticker}_{date_str}_{signal_idx}_{n}".replace("-", "_")

    badge_color = _OUTCOME_COLORS.get(outcome, "#9ca3af")
    badge_text = _OUTCOME_BADGE_TEXT.get(outcome, "")
    move_html = ""
    if pct_move is not None:
        move_color = "#22c55e" if pct_move >= 0 else "#ef4444"
        move_html = (
            f"<span style='color:{move_color};font-weight:800;margin-left:8px'>"
            f"{pct_move:+.2f}%</span>"
        )

    # FIX 2026-06-20 (light "research terminal" theme): switched the chart
    # from dark (#0a0e16) to a white background with a thick 2px black
    # border, per direct mockup feedback ("sleek and has contrast"). Candle
    # green/red and overlay colors are kept (deliberately did NOT go full
    # monochrome — losing the bullish/bearish color cue would make the
    # chart HARDER to read, which cuts against the whole point of this
    # page). Overlay colors were individually darkened where the old pastel
    # tone (built for a dark background) would have washed out on white:
    # VWAP #fb923c -> #d97706, OR lines #60a5fa -> #2563eb, swings handled
    # above (#a78bfa -> #7c3aed).
    html = f"""
    <div style="position:relative;border-radius:8px;overflow:hidden;
                border:2px solid #111827;
                box-shadow:0 2px 10px rgba(0,0,0,0.12);background:#ffffff;">
      <div style="position:absolute;top:10px;left:14px;z-index:10;
                  font-family:-apple-system,'Segoe UI',sans-serif;
                  font-size:0.78rem;font-weight:800;color:#111827;
                  letter-spacing:0.02em">
        {ticker} <span style="color:#6b7280;font-weight:600">· {date_str}</span>
      </div>
      <div style="position:absolute;top:8px;right:14px;z-index:10;
                  font-family:-apple-system,'Segoe UI',sans-serif;">
        <span style="background:{badge_color}1A;border:1.5px solid {badge_color};
                     color:{badge_color};font-size:0.68rem;font-weight:800;
                     letter-spacing:0.06em;padding:3px 9px;border-radius:20px;">
          {badge_text}
        </span>{move_html}
      </div>
      <div id="{chart_id}" style="width:100%; height:{height}px;"></div>
    </div>
    <script src="{_LWC_CDN}"></script>
    <script>
      (function() {{
        const container = document.getElementById("{chart_id}");

        function currentWidth() {{
          return container.clientWidth || container.parentElement.clientWidth || 600;
        }}

        const chart = LightweightCharts.createChart(container, {{
          width: currentWidth(),
          height: {height},
          layout: {{
            background: {{ color: "#ffffff" }},
            textColor: "#1f2328",
            fontFamily: "-apple-system, 'Segoe UI', sans-serif",
          }},
          grid: {{
            vertLines: {{ color: "rgba(17,24,39,0.07)" }},
            horzLines: {{ color: "rgba(17,24,39,0.07)" }},
          }},
          timeScale: {{
            timeVisible: true, secondsVisible: false,
            borderColor: "rgba(17,24,39,0.30)", rightOffset: 4,
          }},
          rightPriceScale: {{ borderColor: "rgba(17,24,39,0.30)" }},
          // FIX 2026-06-20 — "It needs to be interactive, like trading view."
          // These were never explicitly turned on, so the chart could read
          // as a static image that just gets redrawn on every Streamlit
          // rerun. Explicitly enabling scroll/scale + Magnet crosshair
          // (snaps to the nearest candle, like real TradingView) makes the
          // chart respond to the mouse the way a real terminal does.
          crosshair: {{ mode: 1 }},
          handleScroll: {{
            mouseWheel: true, pressedMouseMove: true,
            horzTouchDrag: true, vertTouchDrag: true,
          }},
          handleScale: {{
            axisPressedMouseMove: true, mouseWheel: true, pinch: true,
          }},
        }});

        const candleSeries = chart.addCandlestickSeries({{
          upColor: "#22c55e", downColor: "#ef4444",
          borderUpColor: "#16a34a", borderDownColor: "#dc2626",
          wickUpColor: "#16a34a", wickDownColor: "#dc2626",
          priceFormat: {{ type: "price", precision: 2, minMove: 0.01 }},
        }});
        candleSeries.setData({json.dumps(candle_data)});
        candleSeries.setMarkers({json.dumps(markers)});

        const volumeSeries = chart.addHistogramSeries({{
          priceFormat: {{ type: "volume" }},
          priceScaleId: "",
          scaleMargins: {{ top: 0.82, bottom: 0 }},
        }});
        volumeSeries.setData({json.dumps(volume_data)});

        // ── VWAP overlay — the actual line the strategy's VWAP gate checks
        // against, not just a row in a rules table.
        const vwapData = {json.dumps(vwap_data)};
        if (vwapData.length > 0) {{
          const vwapSeries = chart.addLineSeries({{
            color: "#d97706", lineWidth: 2, lineStyle: 0,
            priceLineVisible: false, lastValueVisible: false,
            crosshairMarkerVisible: false,
          }});
          vwapSeries.setData(vwapData);
        }}

        // ── Opening Range high/low — flat reference levels for the
        // strategies that gate on them (INST_ORB, MID_BRK).
        {f'''candleSeries.createPriceLine({{
          price: {or_high}, color: "#2563eb", lineWidth: 1, lineStyle: 2,
          axisLabelVisible: true, title: "OR High",
        }});''' if or_high is not None else ''}
        {f'''candleSeries.createPriceLine({{
          price: {or_low}, color: "#2563eb", lineWidth: 1, lineStyle: 2,
          axisLabelVisible: true, title: "OR Low",
        }});''' if or_low is not None else ''}

        // ── On-chart callouts — single floating tooltip driven by the
        // chart's own crosshair. See the Python-side comment above for why
        // this replaced both the always-visible floating bubbles AND the
        // static footer strip.
        const callouts = {json.dumps(callouts)};
        if (callouts.length > 0) {{
          const tip = document.createElement("div");
          tip.style.position = "absolute";
          tip.style.maxWidth = "220px";
          tip.style.background = "#ffffff";
          tip.style.borderRadius = "8px";
          tip.style.padding = "8px 11px";
          tip.style.fontFamily = "-apple-system,'Segoe UI',sans-serif";
          tip.style.fontSize = "0.74rem";
          tip.style.lineHeight = "1.35";
          tip.style.color = "#111827";
          tip.style.boxShadow = "0 4px 14px rgba(0,0,0,0.28)";
          tip.style.zIndex = "30";
          tip.style.opacity = "0";
          tip.style.pointerEvents = "none";
          tip.style.transition = "opacity 0.1s";
          container.parentElement.appendChild(tip);

          chart.subscribeCrosshairMove(param => {{
            const hit = (param && param.time !== undefined && param.point)
              ? callouts.find(c => c.time === param.time)
              : null;
            if (!hit) {{
              tip.style.opacity = "0";
              return;
            }}
            tip.style.border = "2px solid " + hit.color;
            tip.innerHTML = "<div style='font-weight:800;color:" + hit.color + ";"
              + "font-size:0.64rem;letter-spacing:0.03em;margin-bottom:3px'>"
              + hit.tag + "</div>" + hit.text;

            const containerW = container.clientWidth || 600;
            let left = param.point.x - 110;
            left = Math.max(4, Math.min(left, containerW - 224));
            const showAbove = param.point.y > 150;
            const top = showAbove ? Math.max(34, param.point.y - 95) : param.point.y + 28;
            tip.style.left = left + "px";
            tip.style.top = top + "px";
            tip.style.opacity = "1";
          }});
        }}

        // ── THE FIX ──────────────────────────────────────────────────────
        // Re-fit every time we learn the real width, not just once at
        // creation (when the iframe may not have been laid out yet). This
        // is what actually prevents the "candles squished into a sliver"
        // bug — see module docstring for the full root-cause explanation.
        function refit() {{
          chart.timeScale().fitContent();
          // Cap bar width so early-session candles (3–6 bars) don't stretch
          // across the full canvas. fitContent() makes each bar as wide as
          // (canvas_width / bar_count), so with 4 bars on a 700px canvas
          // each bar is 175px — enormous. Clamping barSpacing to MAX_BAR_PX
          // keeps bars at a sensible size regardless of bar count.
          try {{
            const MAX_BAR_PX = 8;
            const ts = chart.timeScale();
            const opts = ts.options();
            if ((opts.barSpacing || 999) > MAX_BAR_PX) {{
              ts.applyOptions({{ barSpacing: MAX_BAR_PX }});
            }}
          }} catch(e) {{}}
        }}
        refit();

        const ro = new ResizeObserver(entries => {{
          const w = entries[0].contentRect.width;
          if (w > 0) {{
            chart.applyOptions({{ width: w }});
            refit();
          }}
        }});
        ro.observe(container);

        // Belt-and-suspenders: catch any residual layout race the observer
        // missed (e.g. fonts/CSS finishing load after first paint).
        setTimeout(refit, 60);
        setTimeout(refit, 300);
      }})();
    </script>
    """
    st.iframe(html, height=height + 14)

    caption = (
        f"**{ticker}** real session, {date_str} · direction: {direction} · "
        f"{_OUTCOME_LABEL.get(outcome, 'Real historical outcome')}"
    )
    if reveal_count is not None and reveal_count < len(bars):
        caption += f" · showing bar {reveal_count} of {len(bars)} (step through to see the rest)"
    st.caption(caption)


def render_live_chart(
    df: pd.DataFrame,
    ticker: str,
    chart_title: str = "",
    height: int = 560,
    or_high: float | None = None,
    or_low: float | None = None,
    position_levels: dict | None = None,
    trade_markers: list[dict] | None = None,
    swing_points: list[dict] | None = None,
    show_vwap: bool = True,
    show_vwap_bands: bool = True,
    show_or_zone: bool = True,
    show_position_lines: bool = True,
    show_trade_markers: bool = True,
    show_swings: bool = False,
    show_volume_gate: bool = True,
) -> None:
    """
    Live/intraday chart for the Live Trading page — the SAME TradingView
    (Lightweight Charts) engine as render_strategy_chart() above, but built
    for a continuously-refreshing session instead of a fixed historical
    replay.

    2026-06-21 — replaces the Plotly `_orb_live_fig()` chart in dashboard.py
    per direct request ("If trading view had a overlay open my chart needs
    that option"). Two changes from the old chart:
      1. One big chart instead of a 2x2 "Quad" grid — more room for detail,
         which is most of why the old chart looked cramped next to the video.
      2. Each overlay (VWAP, VWAP bands, OR zone, position lines, trade
         markers, swing structure) is an independent on/off toggle wired in
         dashboard.py — a TradingView-style indicator list — instead of one
         "Simulation Mode" checkbox baking everything together.

    Like render_strategy_chart(), this function does NO trade math — every
    input is plain data the caller already computed. In particular
    `position_levels` must only be passed when the caller has confirmed the
    levels share df's price scale (SIM/ghost trades — see dashboard.py's
    `_levels_on_chart_scale` guard). That guard is what fixed the earlier
    "pink rectangle" bug (option-premium-scale lines drawn on an
    underlying-price-scale chart) in the old chart; reusing the same
    Python-side gate here means that fix carries over instead of having to
    be rediscovered.

    Known simplification vs. the old Plotly chart: the Opening Range is
    drawn as two price lines (not a shaded zone box), and the swing-based
    trendlines/Fibonacci retracement overlay was not ported (Lightweight
    Charts has no direct equivalent of Plotly's add_shape line primitive
    anchored in price+time the way that code needs). The old Plotly function
    is left in dashboard.py, unused but intact, in case either is wanted
    back.
    """
    if df is None or df.empty or len(df) < 2:
        st.warning(f"No bar data to chart for {ticker}.")
        return

    df = df.reset_index(drop=True)

    # ── Gold-highlight the breakout-volume candle (RVOL >= 2.0x) ───────────
    _rvol_max_idx = -1
    if "rvol" in df.columns and not df["rvol"].empty:
        _idx = int(df["rvol"].idxmax())
        if float(df["rvol"].iloc[_idx]) >= 2.0:
            _rvol_max_idx = _idx

    candle_data, volume_data = [], []
    for i, row in df.iterrows():
        t = int(pd.Timestamp(row["time"]).timestamp())
        candle_data.append({
            "time": t, "open": float(row["open"]), "high": float(row["high"]),
            "low": float(row["low"]), "close": float(row["close"]),
        })
        if i == _rvol_max_idx:
            vol_color = "rgba(255,215,0,0.95)"   # gold — breakout-volume candle
        else:
            vol_color = "rgba(34,197,94,0.5)" if row["close"] >= row["open"] else "rgba(239,68,68,0.5)"
        volume_data.append({"time": t, "value": float(row["volume"]), "color": vol_color})

    # ── VWAP line ────────────────────────────────────────────────────────
    vwap_data = []
    if show_vwap and "vwap" in df.columns:
        for _, row in df.iterrows():
            if pd.notna(row["vwap"]):
                vwap_data.append({
                    "time": int(pd.Timestamp(row["time"]).timestamp()),
                    "value": float(row["vwap"]),
                })

    # ── VWAP ±1σ / ±2σ bands ────────────────────────────────────────────
    _band_cols = ("vwap_upper1", "vwap_lower1", "vwap_upper2", "vwap_lower2")
    _has_bands = show_vwap_bands and all(c in df.columns for c in _band_cols)
    band_data = {c: [] for c in _band_cols}
    if _has_bands:
        for _, row in df.iterrows():
            t = int(pd.Timestamp(row["time"]).timestamp())
            for c in _band_cols:
                if pd.notna(row[c]):
                    band_data[c].append({"time": t, "value": float(row[c])})

    # ── Volume rolling average + 200% gate level ────────────────────────
    avg_data, gate_level = [], None
    if show_volume_gate:
        _avg_vol = df["volume"].rolling(10, min_periods=1).mean()
        for ts, v in zip(df["time"], _avg_vol):
            avg_data.append({"time": int(pd.Timestamp(ts).timestamp()), "value": float(v)})
        _avg_last = float(_avg_vol.iloc[-1]) if not _avg_vol.empty else 0.0
        if _avg_last > 0:
            gate_level = _avg_last * 2.0

    # ── Swing-structure (SH/SL) markers ──────────────────────────────────
    markers = []
    if show_swings and swing_points:
        for sp in swing_points:
            if sp["idx"] >= len(df):
                continue
            is_high = sp["type"] == "high"
            markers.append({
                "time": int(pd.Timestamp(df.iloc[sp["idx"]]["time"]).timestamp()),
                "position": "aboveBar" if is_high else "belowBar",
                "color": "#7c3aed", "shape": "arrowDown" if is_high else "arrowUp",
                "text": "SH" if is_high else "SL", "size": 0.55,
            })

    # ── Trade (BUY/SELL) markers + their crosshair tooltips ─────────────
    # tooltips reuses the exact same single-floating-tooltip pattern as
    # render_strategy_chart's signal/entry/exit callouts — hover (or tap)
    # the marked candle to see the trade detail, instead of a permanent
    # Plotly hover box.
    tooltips = []
    if show_trade_markers and trade_markers:
        for m in trade_markers:
            markers.append({
                "time": m["time"],
                "position": "belowBar" if m["side"] == "buy" else "aboveBar",
                "color": m["color"],
                "shape": "arrowUp" if m["side"] == "buy" else "arrowDown",
                "text": m["label"],
            })
            tooltips.append({
                "time": m["time"], "color": m["color"], "tag": m["tag"],
                "text": "<br>".join(m["lines"]),
            })
    markers.sort(key=lambda mk: mk["time"])

    _last_ts = int(pd.Timestamp(df["time"].iloc[-1]).timestamp())
    chart_id = f"lwc_live_{ticker}_{_last_ts}".replace("-", "_").replace(" ", "_")

    title_html = (
        f"<span style='font-size:.78rem;font-weight:800;color:#111827'>{chart_title}</span>"
        if chart_title else ""
    )

    html = f"""
    <div style="position:relative;border-radius:8px;overflow:hidden;
                border:2px solid #111827;
                box-shadow:0 2px 10px rgba(0,0,0,0.12);background:#ffffff;">
      <div style="position:absolute;top:10px;left:14px;z-index:10;
                  font-family:-apple-system,'Segoe UI',sans-serif;">
        {title_html}
      </div>
      <div id="{chart_id}" style="width:100%; height:{height}px;"></div>
    </div>
    <script src="{_LWC_CDN}"></script>
    <script>
      (function() {{
        const container = document.getElementById("{chart_id}");

        function currentWidth() {{
          return container.clientWidth || container.parentElement.clientWidth || 600;
        }}

        const chart = LightweightCharts.createChart(container, {{
          width: currentWidth(),
          height: {height},
          layout: {{
            background: {{ color: "#ffffff" }},
            textColor: "#1f2328",
            fontFamily: "-apple-system, 'Segoe UI', sans-serif",
          }},
          grid: {{
            vertLines: {{ color: "rgba(17,24,39,0.07)" }},
            horzLines: {{ color: "rgba(17,24,39,0.07)" }},
          }},
          timeScale: {{
            timeVisible: true, secondsVisible: false,
            borderColor: "rgba(17,24,39,0.30)", rightOffset: 4,
          }},
          rightPriceScale: {{ borderColor: "rgba(17,24,39,0.30)" }},
          crosshair: {{ mode: 1 }},
          handleScroll: {{
            mouseWheel: true, pressedMouseMove: true,
            horzTouchDrag: true, vertTouchDrag: true,
          }},
          handleScale: {{
            axisPressedMouseMove: true, mouseWheel: true, pinch: true,
          }},
        }});

        const candleSeries = chart.addCandlestickSeries({{
          upColor: "#22c55e", downColor: "#ef4444",
          borderUpColor: "#16a34a", borderDownColor: "#dc2626",
          wickUpColor: "#16a34a", wickDownColor: "#dc2626",
          priceFormat: {{ type: "price", precision: 2, minMove: 0.01 }},
        }});
        candleSeries.setData({json.dumps(candle_data)});
        candleSeries.setMarkers({json.dumps(markers)});

        const volumeSeries = chart.addHistogramSeries({{
          priceFormat: {{ type: "volume" }},
          priceScaleId: "",
          scaleMargins: {{ top: 0.82, bottom: 0 }},
        }});
        volumeSeries.setData({json.dumps(volume_data)});

        // ── VWAP line ──────────────────────────────────────────────────
        const vwapData = {json.dumps(vwap_data)};
        if (vwapData.length > 0) {{
          const vwapSeries = chart.addLineSeries({{
            color: "#d97706", lineWidth: 2.4, lineStyle: 0,
            priceLineVisible: false, lastValueVisible: false,
            crosshairMarkerVisible: false,
          }});
          vwapSeries.setData(vwapData);
        }}

        // ── VWAP sigma bands ───────────────────────────────────────────
        const bandU2 = {json.dumps(band_data.get("vwap_upper2", []))};
        const bandU1 = {json.dumps(band_data.get("vwap_upper1", []))};
        const bandL1 = {json.dumps(band_data.get("vwap_lower1", []))};
        const bandL2 = {json.dumps(band_data.get("vwap_lower2", []))};
        if (bandU1.length > 0) {{
          [[bandU2, "rgba(100,160,255,0.45)", 2],
           [bandU1, "rgba(100,160,255,0.70)", 0],
           [bandL1, "rgba(100,160,255,0.70)", 0],
           [bandL2, "rgba(100,160,255,0.45)", 2]].forEach(([data, color, dash]) => {{
            const s = chart.addLineSeries({{
              color: color, lineWidth: 1, lineStyle: dash,
              priceLineVisible: false, lastValueVisible: false,
              crosshairMarkerVisible: false,
            }});
            s.setData(data);
          }});
        }}

        // ── Opening Range high/low reference lines ─────────────────────
        {f'''candleSeries.createPriceLine({{
          price: {or_high}, color: "#2563eb", lineWidth: 1, lineStyle: 2,
          axisLabelVisible: true, title: "OR High",
        }});''' if (show_or_zone and or_high is not None) else ''}
        {f'''candleSeries.createPriceLine({{
          price: {or_low}, color: "#2563eb", lineWidth: 1, lineStyle: 2,
          axisLabelVisible: true, title: "OR Low",
        }});''' if (show_or_zone and or_low is not None) else ''}

        // ── Open-position lines (Entry / Stop / Target / Trail) ────────
        // Only ever called when dashboard.py has confirmed these share the
        // chart's own price scale — see the Python-side docstring note.
        {f'''candleSeries.createPriceLine({{
          price: {position_levels["entry"]}, color: "#eab308", lineWidth: 1.5,
          lineStyle: 1, axisLabelVisible: true, title: "Entry",
        }});''' if (show_position_lines and position_levels and position_levels.get("entry") is not None) else ''}
        {f'''candleSeries.createPriceLine({{
          price: {position_levels["stop"]}, color: "#dc2626", lineWidth: 1.5,
          lineStyle: 1, axisLabelVisible: true, title: "Stop",
        }});''' if (show_position_lines and position_levels and position_levels.get("stop") is not None) else ''}
        {f'''candleSeries.createPriceLine({{
          price: {position_levels["target"]}, color: "#16a34a", lineWidth: 1.5,
          lineStyle: 1, axisLabelVisible: true, title: "Target",
        }});''' if (show_position_lines and position_levels and position_levels.get("target") is not None) else ''}
        {f'''candleSeries.createPriceLine({{
          price: {position_levels["trail"]}, color: "#9333ea", lineWidth: 1,
          lineStyle: 3, axisLabelVisible: true, title: "Trail",
        }});''' if (show_position_lines and position_levels and position_levels.get("trail") is not None) else ''}

        // ── Volume rolling average + 200% gate ─────────────────────────
        const avgData = {json.dumps(avg_data)};
        if (avgData.length > 0) {{
          const avgSeries = chart.addLineSeries({{
            color: "rgba(255,165,0,.75)", lineWidth: 1.3, lineStyle: 1,
            priceScaleId: "", priceLineVisible: false, lastValueVisible: false,
            crosshairMarkerVisible: false,
          }});
          avgSeries.setData(avgData);
          {f'''avgSeries.createPriceLine({{
            price: {gate_level}, color: "rgba(0,180,60,1)", lineWidth: 1.4,
            lineStyle: 2, axisLabelVisible: true, title: "200% gate",
          }});''' if gate_level is not None else ''}
        }}

        // ── Trade-marker crosshair tooltip (same pattern as Playbooks) ──
        const tooltips = {json.dumps(tooltips)};
        if (tooltips.length > 0) {{
          const tip = document.createElement("div");
          tip.style.position = "absolute";
          tip.style.maxWidth = "230px";
          tip.style.background = "#ffffff";
          tip.style.borderRadius = "8px";
          tip.style.padding = "8px 11px";
          tip.style.fontFamily = "-apple-system,'Segoe UI',sans-serif";
          tip.style.fontSize = "0.74rem";
          tip.style.lineHeight = "1.35";
          tip.style.color = "#111827";
          tip.style.boxShadow = "0 4px 14px rgba(0,0,0,0.28)";
          tip.style.zIndex = "30";
          tip.style.opacity = "0";
          tip.style.pointerEvents = "none";
          tip.style.transition = "opacity 0.1s";
          container.parentElement.appendChild(tip);

          chart.subscribeCrosshairMove(param => {{
            const hit = (param && param.time !== undefined && param.point)
              ? tooltips.find(c => c.time === param.time)
              : null;
            if (!hit) {{ tip.style.opacity = "0"; return; }}
            tip.style.border = "2px solid " + hit.color;
            tip.innerHTML = "<div style='font-weight:800;color:" + hit.color + ";"
              + "font-size:0.64rem;letter-spacing:0.03em;margin-bottom:3px'>"
              + hit.tag + "</div>" + hit.text;

            const containerW = container.clientWidth || 600;
            let left = param.point.x - 115;
            left = Math.max(4, Math.min(left, containerW - 234));
            const showAbove = param.point.y > 150;
            const top = showAbove ? Math.max(34, param.point.y - 95) : param.point.y + 28;
            tip.style.left = left + "px";
            tip.style.top = top + "px";
            tip.style.opacity = "1";
          }});
        }}

        function refit() {{
          chart.timeScale().fitContent();
          // Cap bar width so early-session candles (3–6 bars) don't stretch
          // across the full canvas. fitContent() makes each bar as wide as
          // (canvas_width / bar_count), so with 4 bars on a 700px canvas
          // each bar is 175px — enormous. Clamping barSpacing to MAX_BAR_PX
          // keeps bars at a sensible size regardless of bar count.
          try {{
            const MAX_BAR_PX = 8;
            const ts = chart.timeScale();
            const opts = ts.options();
            if ((opts.barSpacing || 999) > MAX_BAR_PX) {{
              ts.applyOptions({{ barSpacing: MAX_BAR_PX }});
            }}
          }} catch(e) {{}}
        }}
        refit();

        const ro = new ResizeObserver(entries => {{
          const w = entries[0].contentRect.width;
          if (w > 0) {{
            chart.applyOptions({{ width: w }});
            refit();
          }}
        }});
        ro.observe(container);

        setTimeout(refit, 60);
        setTimeout(refit, 300);
      }})();
    </script>
    """
    st.iframe(html, height=height + 14)
