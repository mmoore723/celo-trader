"""
dashboard/css.py — Theme dict and CSS injection.

Import:
    from dashboard.css import T, inject_css
"""
import streamlit as st

T = {
    "bg": "#f9fafb",
    "surface": "#ffffff",
    "surface2": "#f3f4f6",
    "border": "#e5e7eb",
    "accent": "#2563eb", "green": "#16a34a",
    "red": "#dc2626", "yellow": "#d97706", "text": "#111827",
    "muted": "#6b7280", "plot_bg": "#ffffff", "plot_paper": "#f9fafb",
    "purple": "#7c3aed",
}


def inject_css() -> None:
    """Inject all platform CSS. Call once at the top of dashboard.py."""
    # ── CSS — stamp hard hex values so Streamlit defaults can't override ──────────
    st.markdown(f"""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600;700&family=Syne:wght@400;600;700;800&family=Playfair+Display:wght@700;900&display=swap');
    :root {{
      --t-bg:{T["bg"]};--t-surface:{T["surface"]};--t-border:{T["border"]};
      --t-accent:{T["accent"]};--t-green:{T["green"]};--t-red:{T["red"]};
      --t-yellow:{T["yellow"]};--t-text:{T["text"]};--t-muted:{T["muted"]};
    }}
    /* ── COCKPIT LAYOUT — full viewport lock, zero padding ────────── */
    html, body {{
      height:100vh !important;
      overflow:hidden !important;
      margin:0 !important;
      padding:0 !important;
    }}
    [data-testid="stAppViewContainer"] {{
      height:100vh !important;
      overflow:hidden !important;
      padding:0 !important;
    }}
    /* Restore left gutter on the top-level block container so content
       does not clip behind the sidebar border. No overflow:hidden here —
       that was cutting the left edge of text.                          */
    .block-container,
    [data-testid="stMainBlockContainer"] {{
      padding-top:1rem !important;
      padding-right:0 !important;
      padding-bottom:0 !important;
      padding-left:1rem !important;
      gap:4px !important;
      max-width:100% !important;
    }}
    [data-testid="stMain"],
    [data-testid="stMain"] > div:first-child {{
      padding-top:8px !important;
      padding-right:0 !important;
      padding-bottom:0 !important;
      padding-left:1rem !important;
      margin-left:0 !important;
    }}
    [data-testid="stVerticalBlock"],
    [data-testid="stHorizontalBlock"],
    div[data-testid="column"] {{
      padding:0 !important;
      gap:4px !important;
      max-width:100% !important;
    }}
    /* Hard-cap the top Streamlit toolbar / header banner to 100 px.  */
    header[data-testid="stHeader"],
    [data-testid="stHeader"] {{
      max-height:100px !important;
      min-height:0 !important;
      height:auto !important;
      padding:0 !important;
      overflow:hidden !important;
    }}
    /* ── MAIN APP BACKGROUND ──────────────────────────────────────── */
    html,body,.stApp,[data-testid="stAppViewContainer"],[data-testid="stMain"],
    [data-testid="stMainBlockContainer"],.main .block-container {{
      background-color:{T["bg"]} !important;color:{T["text"]} !important;
    }}
    html,body,button,input,select,textarea,[class*="css"],.stMarkdown {{
      font-family:'JetBrains Mono',monospace !important;
    }}
    /* ── Light sidebar ────────────────────────────────────────────────── */
    /* overflow:hidden clips the resize-handle drag widget (right:-6px)
       that otherwise bleeds into the main content area and blocks the first
       ~6-10px of text.                                                     */
    section[data-testid="stSidebar"] {{
      overflow:hidden !important;
    }}
    section[data-testid="stSidebar"],section[data-testid="stSidebar"]>div,
    section[data-testid="stSidebar"]>div>div {{
      background-color:#F0F2F6 !important;
      border-right:1px solid #cccccc !important;
      /* Strip Streamlit's default sidebar padding so we control spacing */
      padding-top:0 !important;
    }}
    /* Sidebar inner content container — set explicit padding so items don't touch edges */
    section[data-testid="stSidebar"] > div > div:first-child {{
      padding:10px 12px 12px !important;
      gap:0 !important;
    }}
    section[data-testid="stSidebar"] * {{ color:#000000 !important; }}
    section[data-testid="stSidebar"] hr {{ border-color:#cccccc !important; }}
    /* Collapse Streamlit's injected vertical gap between sidebar widgets */
    section[data-testid="stSidebar"] [data-testid="stVerticalBlock"],
    section[data-testid="stSidebar"] [data-testid="stVerticalBlockBorderWrapper"] {{
      gap:4px !important;
      row-gap:4px !important;
    }}
    /* Nav buttons: full-width, white bg, black text, subtle border */
    section[data-testid="stSidebar"] .stButton>button {{
      background:#ffffff !important;
      color:#000000 !important;
      border:1px solid #111827 !important;
      border-radius:25px !important;
      font-size:0.82rem !important;
      font-weight:600 !important;
      padding:10px 1px !important;
      width:100% !important;
      text-align:left !important;
      transition:background .12s !important;
      margin-bottom:0 !important;
    }}
    section[data-testid="stSidebar"] .stButton>button:hover {{
      background:#f0f4ff !important;
      color:#1d4ed8 !important;
      border-color:#1d4ed8 !important;
    }}
    /* Active page — high-contrast indigo fill with white text */
    section[data-testid="stSidebar"] .ct-nav-active button,
    section[data-testid="stSidebar"] .stButton>button[aria-pressed="true"] {{
      background:#1d4ed8 !important;
      border-color:#1d4ed8 !important;
      color:#ffffff !important;
      font-weight:700 !important;
    }}
    h1,h2,h3,h4,.stMarkdown h1,.stMarkdown h2,.stMarkdown h3 {{
      font-family:'Syne',sans-serif !important;color:{T["text"]} !important;letter-spacing:-0.02em;
    }}
    [data-testid="stMetricValue"] {{
      font-family:'JetBrains Mono',monospace !important;font-size:1.5rem !important;
      font-weight:700 !important;color:{T["text"]} !important;
    }}
    [data-testid="stMetricLabel"] {{ color:{T["muted"]} !important; }}
    /* ── Force all text to pure black for maximum legibility ──────── */
    p,h1,h2,h3,h4,h5,h6,li,label,td,th,figcaption,span,
    .stMarkdown p,.stMarkdown li,.stMarkdown h1,.stMarkdown h2,
    .stMarkdown h3,.stMarkdown h4,.stMarkdown h5,.stMarkdown h6,
    .stCaption p,
    [data-testid="stCaptionContainer"] p,
    [data-testid="stCaptionContainer"] span,
    [data-testid="stMarkdownContainer"] p,
    [data-testid="stMarkdownContainer"] li,
    [data-testid="stMarkdownContainer"] span,
    [data-testid="stText"] p,
    [data-testid="stMetricLabel"],
    [data-testid="stMetricValue"],
    [data-testid="stMetricDelta"] {{
      color:#000000 !important;
    }}
    /* SVG text inside Plotly charts */
    svg text, .plotly text {{ fill:#000000 !important; color:#000000 !important; }}
    /* Expander header: explicit light bg + dark text at all states */
    [data-testid="stExpander"] details > summary {{
      background-color:{T["surface"]} !important;
      color:{T["text"]} !important;
    }}
    [data-testid="stExpander"] details > summary:hover {{
      background-color:{T["bg"]} !important;
      color:{T["text"]} !important;
    }}
    [data-testid="stExpander"] details > summary p,
    [data-testid="stExpander"] details > summary span {{
      color:{T["text"]} !important;
    }}
    /* ── All input / select / textarea components: white bg, black text ── */
    input,select,textarea,
    .stTextInput>div>div>input,
    .stNumberInput>div>div>input,
    .stSelectbox>div>div>div,
    [data-baseweb="select"]>div,
    [data-baseweb="input"]>div,
    [data-baseweb="textarea"]>div {{
      background-color:#ffffff !important;
      color:#000000 !important;
      border:1px solid #aaaaaa !important;
      border-radius:4px !important;
    }}
    /* Option items inside the dropdown popover */
    [data-baseweb="menu"] li,
    [data-baseweb="popover"] li,
    [role="option"] {{
      background-color:#ffffff !important;
      color:#000000 !important;
    }}
    [data-baseweb="menu"] li:hover,
    [role="option"]:hover {{
      background-color:#f0f2f5 !important;
    }}
    /* Number-input spin buttons */
    .stNumberInput button {{
      background-color:#ffffff !important;
      color:#000000 !important;
      border:1px solid #aaaaaa !important;
    }}
    .stButton>button:not([kind="primary"]) {{
      background-color:{T["surface"]} !important;color:{T["text"]} !important;
      border:1px solid {T["border"]} !important;
    }}
    .stButton>button:not([kind="primary"]):hover {{
      border-color:{T["accent"]} !important;color:{T["accent"]} !important;
    }}
    /* Stop Bot button — always red so it reads as a danger action */
    [data-testid="stButton"]:has(button[data-testid="btn_stop_bot"]) button,
    div:has(> [data-testid="btn_stop_bot"]) button,
    button[key="btn_stop_bot"],
    #btn_stop_bot {{
      background-color:{T["red"]} !important;
      color:#ffffff !important;
      border-color:{T["red"]} !important;
      font-weight:700 !important;
    }}
    /* PANIC CLOSE ALL — sidebar emergency button, red */
    [data-testid="stButton"]:has(button[data-testid="sidebar_panic_close"]) button {{
      background-color:#7f0000 !important;
      color:#ffffff !important;
      border-color:#7f0000 !important;
      font-weight:700 !important;
      font-size:0.8rem !important;
      letter-spacing:0.03em !important;
    }}
    [data-testid="stButton"]:has(button[data-testid="sidebar_panic_close"]) button:hover {{
      background-color:#a00000 !important;
      border-color:#a00000 !important;
    }}
    [data-testid="stButton"]>button[kind="primary"],.stButton>button[kind="primary"] {{
      background-color:{T["red"]} !important;color:white !important;border:none !important;font-weight:700 !important;
    }}
    [data-testid="stExpander"] {{
      background-color:{T["surface"]} !important;border:1px solid {T["border"]} !important;border-radius:6px !important;
    }}
    [data-testid="stDataFrame"],[data-testid="stDataFrame"] *,.stDataFrame {{
      background-color:{T["surface"]} !important;color:{T["text"]} !important;
    }}
    /* AG-grid / dataframe cell text */
    .stDataFrame [role="gridcell"],
    .stDataFrame [role="columnheader"],
    .stDataFrame [role="row"],
    .stDataFrame .dvn-scroller *,
    [data-testid="stDataFrameResizable"] *,
    [data-testid="stDataFrameResizable"] [role="gridcell"] {{
      color:{T["text"]} !important;
      background-color:{T["surface"]} !important;
    }}
    [data-testid="stAlert"] {{
      background-color:{T["surface"]} !important;border-color:{T["border"]} !important;color:{T["text"]} !important;
    }}
    hr {{ border-color:{T["border"]} !important; }}
    .trade-card {{
      background:{T["surface"]} !important;border:1px solid {T["border"]};
      border-radius:8px;padding:1rem 1.2rem;margin-bottom:0.6rem;color:{T["text"]};
    }}
    .status-pill {{
      display:inline-block;padding:2px 10px;border-radius:20px;
      font-size:0.72rem;font-weight:600;letter-spacing:0.05em;text-transform:uppercase;
    }}
    .status-scanning {{ background:rgba(0,200,240,0.12);color:{T["accent"]}; }}
    .status-in_trade {{ background:rgba(26,127,55,0.12);color:{T["green"]}; }}
    .status-halted   {{ background:rgba(207,34,46,0.12);color:{T["red"]}; }}
    .status-idle     {{ background:rgba(88,96,105,0.12);color:{T["muted"]}; }}
    .status-standby  {{ background:rgba(180,120,0,0.12);color:#b27800; }}
    .journal-table {{ overflow-x:auto; }}
    code,pre {{ background:{T["surface"]} !important;color:{T["accent"]} !important; }}
    
    /* ── METRIC CARDS ─────────────────────────────────────────────── */
    .mc{{background:{T["surface"]};border:1px solid {T["border"]};border-radius:6px;padding:10px 12px;margin-top:0;margin-bottom:0}}
    .ml{{font-size:.57rem;color:#374151;text-transform:uppercase;letter-spacing:.09em;margin-bottom:3px;font-weight:700}}
    .mv{{font-size:1rem;font-weight:700;color:{T["text"]}}}
    .md{{font-size:.57rem;color:{T["muted"]};margin-top:2px}}
    .mrow{{display:grid;gap:6px;margin-bottom:0;padding:4px 2px;box-sizing:border-box;width:100%;overflow:hidden}}
    .m8{{grid-template-columns:repeat(8,1fr)}}
    .m6{{grid-template-columns:repeat(6,1fr)}}
    .m5{{grid-template-columns:repeat(5,1fr)}}
    .m4{{grid-template-columns:repeat(4,1fr)}}
    .m3{{grid-template-columns:repeat(3,1fr)}}
    /* Compact card values in 8-col grid so text doesn't overflow */
    .mrow.m8 .mv{{font-size:.8rem!important}}
    .mrow.m8 .ml{{font-size:.5rem!important}}
    .mrow.m8 .md{{font-size:.48rem!important}}
    .mrow.m8 .mc{{padding:7px 8px!important}}
    
    /* ── COLOUR HELPERS ───────────────────────────────────────────── */
    .c-grn{{color:{T["green"]}!important}}
    .c-red{{color:{T["red"]}!important}}
    .c-acc{{color:{T["accent"]}!important}}
    .c-yel{{color:{T["yellow"]}!important}}
    .c-pur{{color:{T["purple"]}!important}}
    .c-mut{{color:{T["muted"]}!important}}
    
    /* ── CELO TRADER BRANDING — luxury light mode ────────────────────── */
    /* Deep navy metallic text on cool-white card with left accent stripe. */
    .ct-brand {{
      font-family:'Playfair Display',Georgia,serif !important;
      font-weight:900;
      font-size:clamp(1.6rem,3.5vw,2.4rem);
      letter-spacing:0.18em;
      text-align:center;
      line-height:1.05;
      /* Navy → midnight → charcoal: luxury without going dark-mode */
      background:linear-gradient(
        180deg,
        #0a2540 0%,
        #0f2d52 25%,
        #1a3a5c 50%,
        #0f2d52 75%,
        #0a2540 100%
      );
      -webkit-background-clip:text;
      -webkit-text-fill-color:transparent;
      background-clip:text;
      filter:drop-shadow(0 1px 0 rgba(255,255,255,0.9));
      margin:0;
      padding:0;
      user-select:none;
    }}
    .ct-brand-wrap {{
      background:linear-gradient(135deg,#f8faff 0%,#ffffff 55%,#f4f7fd 100%);
      border:1px solid #dde4f0;
      border-left:3px solid #0a2540;
      border-radius:8px;
      padding:6px 20px 5px;
      margin-bottom:4px;
      text-align:center;
      box-shadow:0 2px 12px rgba(10,37,64,0.09),0 1px 3px rgba(0,0,0,0.04);
    }}
    .ct-sub {{
      font-family:'JetBrains Mono',monospace !important;
      font-size:0.55rem;
      letter-spacing:0.30em;
      color:#4a6080;
      text-transform:uppercase;
      margin-top:2px;
      margin-bottom:2px;
    }}
    
    /* ── CARD SHADOW SYSTEM — professional depth without hard outlines ─ */
    /* Cards are separated by elevation (shadow), not black borders.     */
    /* This mirrors Stripe/Linear/Vercel's design language.              */
    [data-testid="stPlotlyChart"] > div {{
      border-radius:8px;
      overflow:hidden;
      box-shadow:0 1px 3px rgba(0,0,0,0.08),0 1px 2px rgba(0,0,0,0.05);
    }}
    [data-testid="stExpander"] {{
      border:1px solid {T["border"]} !important;
      border-radius:8px !important;
      box-shadow:0 1px 2px rgba(0,0,0,0.05) !important;
    }}
    .trade-card,.mc {{
      border:1px solid {T["border"]} !important;
      box-shadow:0 1px 2px rgba(0,0,0,0.04) !important;
    }}
    
    /* ── TOPBAR STRIP ─────────────────────────────────────────────── */
    .live-topbar{{
      background:linear-gradient(135deg,#f8faff 0%,#ffffff 60%,#f4f7fd 100%);
      border:1px solid #dde4f0;border-radius:6px;
      display:flex;align-items:center;padding:5px 12px;gap:8px;margin-bottom:4px;
      flex-wrap:nowrap;overflow:hidden;
      box-shadow:0 1px 4px rgba(10,37,64,0.07);
    }}
    .tb-ticker{{font-family:'Syne',sans-serif;font-size:.95rem;font-weight:700;color:#0a2540}}
    .tb-pnl-lbl{{font-size:.58rem;font-weight:700;color:#7a93ae;text-transform:uppercase;letter-spacing:.08em;line-height:1}}
    .tb-pnl-val{{font-size:.9rem;font-weight:800;letter-spacing:-.01em;line-height:1.1}}
    .tb-price{{font-size:.82rem;font-weight:600;color:{T["text"]}}}
    .tb-chg{{font-size:.7rem;font-weight:600}}
    .tb-sep{{width:1px;height:18px;background:#dde4f0;flex-shrink:0}}
    .tb-right{{display:flex;align-items:center;gap:6px;font-size:.62rem;color:{T["muted"]}}}
    .live-dot{{width:6px;height:6px;border-radius:50%;background:{T["green"]};
      display:inline-block;animation:ctpulse 2s infinite}}
    @keyframes ctpulse{{0%,100%{{opacity:1}}50%{{opacity:.4}}}}
    
    /* ── TIMEFRAME RADIO — compact pill style, no native dot ─────── */
    /* The native Streamlit radio circle bleeds into adjacent rows.
       We hide it and restyle the container as a flat pill strip.     */
    div[data-testid="stRadio"] {{
      padding:0!important;
      margin:0!important;
    }}
    div[data-testid="stRadio"] > div {{
      gap:0!important;
      flex-direction:row!important;
      align-items:center!important;
    }}
    div[data-testid="stRadio"] label {{
      padding:3px 10px!important;
      border:1px solid {T["border"]}!important;
      border-radius:4px!important;
      margin-right:4px!important;
      font-size:.72rem!important;
      font-weight:600!important;
      cursor:pointer!important;
      background:{T["surface"]}!important;
      color:{T["text"]}!important;
    }}
    div[data-testid="stRadio"] label:has(input:checked) {{
      background:#dbeafe!important;
      border-color:#0969da!important;
      color:#0969da!important;
    }}
    /* Hide the raw radio circle button */
    div[data-testid="stRadio"] input[type="radio"] {{
      display:none!important;
    }}
    
    /* ── SIGNAL PILLS ─────────────────────────────────────────────── */
    .pill{{padding:2px 8px;border-radius:20px;font-size:.6rem;font-weight:600;
      letter-spacing:.05em;text-transform:uppercase;display:inline-block}}
    .pill-bull{{background:rgba(26,127,55,.12);color:{T["green"]};border:1px solid rgba(26,127,55,.25)}}
    .pill-bear{{background:rgba(207,34,46,.12);color:{T["red"]};border:1px solid rgba(207,34,46,.25)}}
    .pill-wait{{background:rgba(154,103,0,.10);color:{T["yellow"]};border:1px solid rgba(154,103,0,.25)}}
    
    /* ── BADGES ───────────────────────────────────────────────────── */
    .badge{{display:inline-block;padding:2px 7px;border-radius:999px;font-size:.58rem;font-weight:600}}
    .b-bull{{background:rgba(26,127,55,.12);color:{T["green"]}}}
    .b-bear{{background:rgba(207,34,46,.12);color:{T["red"]}}}
    .b-man {{background:rgba(154,103,0,.10);color:{T["yellow"]}}}
    .b-call{{background:rgba(26,127,55,.12);color:{T["green"]}}}
    .b-put {{background:rgba(207,34,46,.12);color:{T["red"]}}}
    .b-tp  {{background:rgba(26,127,55,.10);color:{T["green"]}}}
    .b-sl  {{background:rgba(207,34,46,.10);color:{T["red"]}}}
    
    /* ── CHECKBOX IN RIGHT PANEL — pad so it doesn't touch the edge ─ */
    div[data-testid="column"]:last-child [data-testid="stCheckbox"] {{
      padding:4px 6px!important;
      border-radius:4px!important;
      background:{T["surface"]}!important;
      border:1px solid {T["border"]}!important;
      margin-top:2px!important;
    }}
    div[data-testid="column"]:last-child [data-testid="stCheckbox"] label p {{
      font-size:.72rem!important;
      font-weight:600!important;
    }}
    
    /* ── POSITION PANEL ───────────────────────────────────────────── */
    /* col_pos is a narrow column — panel must fill without overflow.
       All child elements use box-sizing:border-box so padding never
       pushes content outside the column boundary.                      */
    .pos-panel{{
      background:{T["surface"]};border:1px solid {T["border"]};
      border-radius:6px;font-family:'JetBrains Mono',monospace;
      box-sizing:border-box;width:100%;overflow:hidden;
      margin-top:0;
    }}
    .pos-head{{
      display:flex;align-items:center;justify-content:space-between;
      padding:8px 12px;border-bottom:1px solid {T["border"]};
      box-sizing:border-box;
    }}
    .pos-ht{{font-size:.62rem;color:{T["muted"]};text-transform:uppercase;letter-spacing:.08em}}
    .pos-body{{
      padding:10px 12px 12px 12px;
      box-sizing:border-box;
      display:flex;flex-direction:column;gap:0;
    }}
    .pos-sym{{
      font-size:.80rem;font-weight:600;color:{T["accent"]};
      word-break:break-all;margin-bottom:1px;
    }}
    .pos-sub{{font-size:.58rem;color:{T["muted"]};margin-bottom:8px}}
    .pos-divider{{height:1px;background:{T["border"]};margin:8px 0;flex-shrink:0}}
    .prow{{
      display:flex;justify-content:space-between;align-items:baseline;
      margin-bottom:4px;font-size:.65rem;box-sizing:border-box;
    }}
    .pk{{color:{T["muted"]}}}
    .pv{{font-weight:600;color:{T["text"]}}}
    .pnl-box{{
      border-radius:4px;padding:7px 8px;text-align:center;
      margin:6px 0;box-sizing:border-box;
    }}
    .pnl-lbl{{font-size:.56rem;text-transform:uppercase;letter-spacing:.09em;margin-bottom:2px}}
    .pnl-num{{font-size:1.1rem;font-weight:700;line-height:1.2}}
    .prog-head{{
      display:flex;justify-content:space-between;
      font-size:.55rem;color:{T["muted"]};margin-bottom:3px;
    }}
    .prog-track{{
      height:5px;background:{T["border"]};border-radius:3px;
      overflow:hidden;margin-bottom:8px;
    }}
    .prog-fill{{height:100%;border-radius:3px}}
    
    /* ── SIGNAL BASIS ROWS ────────────────────────────────────────── */
    .sig-section{{
      font-size:.56rem;color:{T["muted"]};text-transform:uppercase;
      letter-spacing:.08em;margin:8px 0 5px;
    }}
    .sig-row{{
      display:flex;justify-content:space-between;align-items:center;
      padding:3px 0;border-bottom:1px solid {T["border"]};
      font-size:.63rem;box-sizing:border-box;gap:4px;
    }}
    .sig-row:last-child{{border-bottom:none}}
    .sig-k{{color:{T["text"]};opacity:.8;font-size:.62rem;white-space:nowrap}}
    
    /* ── HAMBURGER SIDEBAR TOGGLE (light mode only) ──────────────── */
    /* White background, #333 border, minimum 32 × 32 px tap area.    */
    [data-testid="stSidebarCollapsedControl"] {{
      position:fixed!important;
      top:8px!important;
      left:8px!important;
      z-index:999999!important;
      display:flex!important;
      align-items:center!important;
      justify-content:center!important;
      opacity:1!important;
      background:#ffffff!important;
      border:2px solid #333333!important;
      border-radius:8px!important;
      min-width:36px!important;
      min-height:36px!important;
      padding:0!important;
      box-shadow:0 2px 8px rgba(0,0,0,.15)!important;
      transition:box-shadow .15s ease,transform .1s ease!important;
    }}
    [data-testid="stSidebarCollapsedControl"]:hover {{
      box-shadow:0 4px 14px rgba(0,0,0,.25)!important;
      transform:scale(1.06)!important;
    }}
    [data-testid="stSidebarCollapsedControl"] button svg {{
      display:none!important;
    }}
    [data-testid="stSidebarCollapsedControl"] button::before {{
      content:"☰"!important;
      font-size:20px!important;
      font-weight:900!important;
      color:#222222!important;
      line-height:1!important;
      padding:8px 10px!important;
      display:block!important;
      letter-spacing:1px!important;
    }}
    [data-testid="stSidebarCollapsedControl"] button {{
      background:transparent!important;
      border:none!important;
      cursor:pointer!important;
      padding:0!important;
      min-width:36px!important;
      min-height:36px!important;
      display:flex!important;
      align-items:center!important;
      justify-content:center!important;
    }}
    /* Inside sidebar: simple close chevron — keep it understated */
    [data-testid="stSidebarCollapseButton"] button {{
      background:transparent!important;
      border:none!important;
    }}
    [data-testid="stSidebarCollapseButton"] button svg {{
      fill:{T["muted"]}!important;
    }}
    /* Inside open sidebar: keep the native close button but style it */
    [data-testid="stSidebarCollapseButton"] button {{
      background:transparent!important;
      border:none!important;
    }}
    [data-testid="stSidebarCollapseButton"] button svg {{
      fill:{T["muted"]}!important;
    }}
    /* Make the black Streamlit header bar invisible without hiding its children.
       The sidebar toggle lives inside it — hiding the element kills the button. */
    header[data-testid="stHeader"] {{
      background:transparent!important;
      border-bottom:none!important;
      box-shadow:none!important;
    }}
    /* Hide the deploy/settings toolbar icons specifically */
    [data-testid="stToolbarActions"],
    [data-testid="stDecoration"] {{
      display:none!important;
    }}
    /* Reduce top padding now that the header is gone;
       keep just enough room for the hamburger button */
    [data-testid="stMain"] > div:first-child {{
      padding-top:8px!important;
    }}
    
    /* ── PLOTLY CHART WRAPPER — kill all Streamlit padding ──────── */
    [data-testid="stPlotlyChart"] {{
      margin-top:-25px!important;
      margin-right:0!important;
      margin-bottom:0!important;
      margin-left:0!important;
      padding:0!important;
      line-height:0!important;
      display:block!important;
    }}
    /* Collapse the vertical block gap between adjacent chart elements */
    [data-testid="stVerticalBlockBorderWrapper"],
    [data-testid="stVerticalBlock"] {{
      gap:0!important;
      row-gap:0!important;
      margin-top:0!important;
    }}
    /* Kill default Streamlit margins across all block containers */
    [data-testid="stMarkdownContainer"],
    [data-testid="stElementContainer"],
    [data-testid="stWidgetLabel"] {{
      margin-top:0!important;
      margin-bottom:0!important;
    }}
    /* Plotly chart element — remove bottom gap so signal pill sits flush */
    [data-testid="stPlotlyChart"] {{
      margin-bottom:0!important;
      padding-bottom:0!important;
    }}
    /* Primary metric delta — 14pt for legibility */
    [data-testid="stMetricDelta"] {{
      font-size:14pt!important;
    }}
    
    /* ── CHART CONTAINER ─────────────────────────────────────────── */
    .chart-wrap{{background:{T["surface"]};border:1px solid {T["border"]};
      border-radius:6px;padding:0;margin-bottom:0}}
    .chart-wrap [data-testid="stPlotlyChart"]{{margin:0!important;padding:0!important}}
    .chart-hd{{display:flex;align-items:center;justify-content:space-between;
      padding:7px 12px;border-bottom:1px solid {T["border"]}}}
    .chart-ht{{font-size:.62rem;color:{T["muted"]};text-transform:uppercase;letter-spacing:.08em}}
    .legend{{display:flex;gap:10px}}
    .leg{{display:flex;align-items:center;gap:4px;font-size:.57rem;color:{T["muted"]}}}
    .leg-line{{width:12px;height:2px;border-radius:1px;display:inline-block}}
    
    /* ── PRICE TICKER BAR ─────────────────────────────────────────── */
    @keyframes ticker-scroll {{
      0%   {{ transform: translateX(0); }}
      100% {{ transform: translateX(-50%); }}
    }}
    .ticker-wrap {{
      position:fixed;bottom:0;left:0;right:0;z-index:9999;
      background:#ffffff;border-top:1px solid #e5e7eb;
      box-shadow:0 -2px 8px rgba(0,0,0,0.06);
      height:32px;overflow:hidden;display:flex;align-items:center;
    }}
    .ticker-track {{
      display:flex;align-items:center;white-space:nowrap;
      animation:ticker-scroll 40s linear infinite;
      gap:0;
    }}
    .ticker-item {{
      display:inline-flex;align-items:center;gap:6px;
      padding:0 24px;font-size:12px;font-family:'JetBrains Mono',monospace;
      border-right:1px solid #cccccc;
    }}
    /* Scoped under .ticker-wrap so specificity = 0-2-0 (20 pts).
       Beats [data-testid="stMarkdownContainer"] span at 0-1-1 (11 pts)
       even when both carry !important.                                    */
    .ticker-wrap .ticker-sym {{ color:#111827!important;font-weight:700; }}
    .ticker-wrap .ticker-px  {{ color:#374151!important; }}
    .ticker-wrap .ticker-up  {{ color:#16a34a!important;font-weight:700; }}
    .ticker-wrap .ticker-dn  {{ color:#dc2626!important;font-weight:700; }}
    </style>
    """, unsafe_allow_html=True)
