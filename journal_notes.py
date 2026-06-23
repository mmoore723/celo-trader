"""
journal_notes.py
─────────────────────────────────────────────────────────────────────────────
Builds a plain-language "Notes" cell for the Trade Journal table.

For every trade it produces:
  1. A short, plain-English TL;DR clamped to 2 lines (always visible)
  2. A "📝 Full breakdown" link that opens a notepad-styled popup with:
       - WHY the bot entered      (per-strategy entry rationale)
       - WHAT it noticed           (per-strategy market context)
       - WHY the bot exited        (decoded from the raw exit_reason string)
       - WHAT it could do better   (losses only — rendered in red)

Language is kept deliberately non-technical — no "RVOL", "VWAP", "dynamic
stop", "structural stop", "R:R", "premium", etc. Everything is written the
way you'd explain it to a friend who doesn't trade.

The output is an HTML snippet intended for Streamlit's unsafe_allow_html
table renderer (_html_table in dashboard.py), which injects raw cell HTML
without escaping. The popup is a pure CSS ":target" modal — clicking the
"Full breakdown" link navigates to a same-page anchor (#cm-note-<id>) which
makes the matching <div> visible via CSS, and "✕ Close" navigates back to an
empty anchor to hide it again. No JavaScript is required, so this works
inside Streamlit's st.markdown(unsafe_allow_html=True) rendering.

NOTE_MODAL_CSS must be injected ONCE (anywhere) on the page via
st.markdown(NOTE_MODAL_CSS, unsafe_allow_html=True) for the popup and the
2-line clamp to render correctly.

No external dependencies (no pandas/streamlit imports) so this module stays
lightweight and safe to import from dashboard.py without side effects.
"""

import re


# ── One-time CSS for the Notes column (2-line clamp + notepad popup) ─────────
# Inject this ONCE per page render via:
#     st.markdown(NOTE_MODAL_CSS, unsafe_allow_html=True)
NOTE_MODAL_CSS = """
<style>
/* Clamp the always-visible TL;DR to 2 lines, ellipsis if longer */
.cm-note-tldr {
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
    text-overflow: ellipsis;
    font-size: 0.82rem;
    line-height: 1.35;
    min-width: 280px;  /* guarantees ~5 words per line x 2 lines */
}
/* "Full breakdown" link */
.cm-note-link {
    display: inline-block;
    margin-top: 3px;
    font-size: 0.76rem;
    color: #0969da;
    text-decoration: none;
    cursor: pointer;
}
.cm-note-link:hover { text-decoration: underline; }

/* Pure-CSS modal overlay — shown only when the URL hash matches this row's id */
.cm-note-overlay {
    display: none;
    position: fixed;
    top: 0; left: 0; right: 0; bottom: 0;
    width: 100%; height: 100%;
    background: rgba(0, 0, 0, 0.45);
    z-index: 9999;
    align-items: center;
    justify-content: center;
}
.cm-note-overlay:target {
    display: flex;
}

/* Notepad-styled popup card: cream paper + ruled lines + red margin line */
.cm-note-paper {
    position: relative;
    background-color: #fffef0;
    background-image: repeating-linear-gradient(
        to bottom,
        transparent 0px, transparent 27px,
        #cfe3f5 27px, #cfe3f5 28px
    );
    border-left: 4px solid #ff8a8a;
    border-radius: 4px;
    box-shadow: 0 12px 40px rgba(0, 0, 0, 0.35);
    width: 90%;
    max-width: 460px;
    max-height: 75vh;
    overflow-y: auto;
    padding: 20px 22px 20px 34px;
    font-size: 0.88rem;
    line-height: 28px;
    color: #2b2b2b;
    text-align: left;
}
.cm-note-paper h4 {
    margin: 0 0 2px 0;
    font-size: 0.95rem;
    line-height: 28px;
}
/* Inline setting names (e.g. ORB_STOP_PCT) inside the technical tip */
.cm-note-paper code {
    background: rgba(0, 0, 0, 0.06);
    border-radius: 3px;
    padding: 1px 4px;
    font-size: 0.82rem;
    line-height: normal;
}
.cm-note-close {
    position: absolute;
    top: 10px; right: 12px;
    background: #eaeef2;
    color: #57606a;
    border-radius: 4px;
    padding: 2px 9px;
    font-size: 0.76rem;
    text-decoration: none;
    line-height: normal;
}
.cm-note-close:hover { background: #d8dee4; }
</style>
"""


# ── Per-strategy entry rationale ──────────────────────────────────────────────
# Keyed by strategy_id (matches strategy_router.py's _STRAT_NAMES keys) then
# by option_type ("call" = bullish bias, "put" = bearish bias).
# "short" = a few words for the TL;DR line. "long" = full plain-English sentence.
_ENTRY: dict[str, dict[str, dict[str, str]]] = {
    "INST_ORB": {
        "call": {
            "short": "an early breakout above the day's opening range",
            "long":  "Right after the market opened, price pushed above its early "
                     "trading range on much busier-than-normal trading — the bot "
                     "read that as buyers taking control right out of the gate.",
        },
        "put": {
            "short": "an early breakdown below the day's opening range",
            "long":  "Right after the market opened, price dropped below its early "
                     "trading range on much busier-than-normal trading — the bot "
                     "read that as sellers taking control right out of the gate.",
        },
    },
    "BOS_MSS": {
        "call": {
            "short": "a break above a recent high point",
            "long":  "Price broke above a recent high point, which the bot reads "
                     "as a sign the short-term trend is turning upward.",
        },
        "put": {
            "short": "a break below a recent low point",
            "long":  "Price broke below a recent low point, which the bot reads "
                     "as a sign the short-term trend is turning downward.",
        },
    },
    "VWAP_PB": {
        "call": {
            "short": "a bounce off the day's average price",
            "long":  "Price dipped down to roughly the average price traded so far "
                     "today and then bounced back up — the bot read that as buyers "
                     "stepping back in at a 'fair' price.",
        },
        "put": {
            "short": "a rejection at the day's average price",
            "long":  "Price rallied up to roughly the average price traded so far "
                     "today and then turned back down — the bot read that as sellers "
                     "stepping back in at a 'fair' price.",
        },
    },
    "FVG": {
        "call": {
            "short": "a move back into a price gap from earlier, leaning higher",
            "long":  "Earlier in the day, price jumped so fast it skipped over a "
                     "small price range without trading there. Price was now moving "
                     "back toward that empty area, and the overall direction favored "
                     "the upside.",
        },
        "put": {
            "short": "a move back into a price gap from earlier, leaning lower",
            "long":  "Earlier in the day, price jumped so fast it skipped over a "
                     "small price range without trading there. Price was now moving "
                     "back toward that empty area, and the overall direction favored "
                     "the downside.",
        },
    },
    "MID_BRK": {
        "call": {
            "short": "a midday breakout to the upside",
            "long":  "Around midday, price had been moving sideways in a tight range "
                     "and then broke out to the upside on a burst of trading activity "
                     "— the bot read that as the market picking a new direction.",
        },
        "put": {
            "short": "a midday breakdown to the downside",
            "long":  "Around midday, price had been moving sideways in a tight range "
                     "and then broke down to the downside on a burst of trading "
                     "activity — the bot read that as the market picking a new direction.",
        },
    },
    "AFT_REV": {
        "call": {
            "short": "a late-day bounce off a low",
            "long":  "Late in the trading day, price turned back up after dropping, "
                     "with trading activity picking back up — the bot read that as the "
                     "sell-off running out of steam and a bounce starting.",
        },
        "put": {
            "short": "a late-day pullback from a high",
            "long":  "Late in the trading day, price turned back down after rising, "
                     "with trading activity picking back up — the bot read that as the "
                     "rally running out of steam and a pullback starting.",
        },
    },
    "TREND_CONT": {
        "call": {
            "short": "the existing uptrend resuming after a pause",
            "long":  "The market had been trending higher for a while, paused "
                     "briefly, and then kept moving up — the bot read that as "
                     "'more of the same' continuing.",
        },
        "put": {
            "short": "the existing downtrend resuming after a pause",
            "long":  "The market had been trending lower for a while, paused "
                     "briefly, and then kept moving down — the bot read that as "
                     "'more of the same' continuing.",
        },
    },
    "CHAN_BREAK": {
        "call": {
            "short": "a bounce off the bottom of its recent trading range",
            "long":  "Price reached the bottom edge of its recent trading range and "
                     "bounced back up off it — the bot read that as a bounce inside "
                     "a sideways range.",
        },
        "put": {
            "short": "a rejection at the top of its recent trading range",
            "long":  "Price reached the top edge of its recent trading range and "
                     "turned back down — the bot read that as a rejection inside "
                     "a sideways range.",
        },
    },
}

# ── Per-strategy market observation (direction-agnostic, plain English) ──────
_OBSERVATIONS: dict[str, str] = {
    "INST_ORB":   "Trading activity early in the day was much busier than usual — "
                  "that's the bot's strongest clue that a move is for real and not just noise.",
    "BOS_MSS":    "Trading picked up right as price broke through that key level, "
                  "which the bot takes as a sign other traders are reacting to the same point.",
    "VWAP_PB":    "Price was right around its average price for the day, with more "
                  "trading than usual — a spot the bot considers a good place for "
                  "the price to turn.",
    "FVG":        "There was a leftover price gap from earlier that hadn't been "
                  "revisited yet, and trading activity supported price moving back into it.",
    "MID_BRK":    "Trading was busier than the typical midday lull, suggesting real "
                  "interest instead of the market just drifting sideways.",
    "AFT_REV":    "Trading activity picked up late in the day near an extreme price "
                  "for the session, which the bot reads as traders repositioning before the close.",
    "TREND_CONT": "The bigger-picture trend was clearly intact, and the pause in "
                  "price was small before it kept moving the same direction.",
    "CHAN_BREAK": "Price reached the edge of a clear, recent trading range and showed "
                  "a strong reversal candle, with trading activity supporting the bounce.",
}

# Fallback text for any strategy_id not in the dicts above (keeps this module
# forward-compatible if a new strategy is added to strategy_router.py later).
_DEFAULT_ENTRY_SHORT = "a setup matching this strategy's rules"
_DEFAULT_ENTRY_LONG  = "The bot spotted a setup matching this strategy's entry rules and took the trade."
_DEFAULT_OBSERVATION = "Price and trading activity lined up with what this strategy looks for."


# ── Exit-reason → short phrase (for TL;DR) and full sentence ─────────────────
def _exit_short(exit_reason: str) -> str:
    """One short phrase describing why the trade ended, for the TL;DR line."""
    er = exit_reason.lower()
    if "time_box_45m" in er:
        return "after its 45-minute time limit"
    if "stage1_50pct" in er:
        return "after hitting its first profit goal"
    if "stage2_break_even" in er or "stage2_stop_be" in er:
        return "at break-even after banking early profit"
    if "structural_stop" in er:
        return "after price broke a key level"
    if "dynamic_stop" in er:
        return "after hitting its stop-loss"
    if "kill_lock_force_close" in er:
        return "when the daily loss limit kicked in"
    if "manual" in er:
        return "manually"
    if "panic" in er:
        return "on an emergency close"
    return "when its exit rule triggered"


def _exit_long(exit_reason: str) -> str:
    """
    Translate the raw exit_reason string (see trading_logic.py's _reason_map
    and risk.py's dynamic_stop_*pct labels) into a plain-English sentence —
    no "premium", "dynamic stop", "structural stop", etc.
    """
    if not exit_reason:
        return "This trade is still open."

    er = exit_reason.lower()

    if "time_box_45m" in er:
        return ("The trade had been open for 45 minutes without reaching its goal, "
                "so the bot closed it automatically. This is a safety rule that "
                "limits how long money sits in one trade.")
    if "stage1_50pct" in er:
        return ("The trade reached its first profit goal, so the bot locked in "
                "some profit by selling part of the position.")
    if "stage2_break_even" in er or "stage2_stop_be" in er:
        return ("After locking in some profit earlier, the rest of the trade was "
                "closed for no further gain or loss — protecting the profit already banked.")
    if "structural_stop" in er:
        return ("Price moved back through a level the bot was watching as its "
                "'this idea is wrong' point, so it exited.")
    if "dynamic_stop" in er:
        m = re.search(r"dynamic_stop_(\d+)pct", er)
        if m:
            return (f"Price moved against the trade enough to lose about {m.group(1)}% "
                    f"of what was risked, so the bot exited to limit the damage.")
        return ("Price moved against the trade enough to trigger the bot's "
                "stop-loss, so it exited to limit the damage.")
    if "kill_lock_force_close" in er:
        return ("The bot hit its daily loss limit, so it automatically closed every "
                "open trade for the rest of the day to stop further losses.")
    if "manual" in er:
        return "The trade was closed manually."
    if "panic" in er:
        return "An emergency stop was triggered to protect the account."

    return f"The trade was closed ({exit_reason})."


# ── Improvement tip for losing trades (plain English) ────────────────────────
def _improvement_tip(exit_reason: str) -> str:
    """
    Suggest, in plain language, what could be done better next time —
    only ever shown for trades with realized_pnl <= 0.
    """
    er = (exit_reason or "").lower()

    if "time_box_45m" in er:
        return ("This trade went nowhere and ran out the clock. The bot could be "
                "pickier about which setups it takes — for example, only entering "
                "when trading activity is unusually heavy.")
    if "dynamic_stop" in er or "structural_stop" in er:
        return ("The bot guessed the wrong direction here. It could wait for one "
                "more sign of confirmation before entering, or risk less money on "
                "this type of setup.")
    if "kill_lock_force_close" in er:
        return ("This loss happened during a rough stretch that triggered the "
                "daily stop. The bot could look at whether it took too many trades "
                "back-to-back during a choppy day.")
    if "stage2_break_even" in er or "stage2_stop_be" in er:
        return ("Profit was given back after the first target. The bot could lock "
                "in a bigger share of the profit earlier instead of letting the "
                "rest ride.")

    return ("The bot could look back at the price chart around this trade for "
            "early warning signs — like trading slowing down or a reversal "
            "candle — that the move was losing steam.")


# ── Technical "could do better" — names the actual setting to change ─────────
def _live_risk_constants() -> dict:
    """
    Read the actual current values of every dial _technical_tip() mentions,
    straight from risk.py / config.py, instead of hardcoding numbers in the
    text below.

    FIX 2026-06-22: the text used to hardcode "30%" for ORB_STOP_PCT and
    "1.2x" for volume_filter_multiplier — both went stale the moment those
    constants were tuned elsewhere (ORB_STOP_PCT was lowered to 20% back
    when the hard stop was tightened; the default volume_filter_multiplier
    has always been 2.0x, that number was simply wrong). Hardcoded numbers
    in a note that's supposed to teach the user how to change the bot will
    silently drift out of sync every time risk.py/config.py changes — reading
    them live is the only way this stays correct without remembering to
    update this file every time. Falls back to the values that were true at
    the time this comment was written if either module can't be imported
    (keeps this module's "no hard dependencies" property from the docstring).
    """
    _defaults = {
        "stop_pct": 20, "tighten_interval": 15, "tighten_step": 5,
        "floor_pct": 10, "stage1_gain": 50, "daily_cap": 10,
        "kill_lock_hours": 24, "rr_small": 1.2, "rr_pro": 1.6,
        "vol_mult": 2.0,
    }
    try:
        from risk import RiskManager
        from config import (
            DAILY_LOSS_HARD_CAP_PCT, KILL_LOCK_HOURS,
            MIN_RR_RATIO_SMALL_ACCOUNT, MIN_RR_RATIO_PROFESSIONAL,
            get_settings,
        )
        _settings = get_settings()
        return {
            "stop_pct":         round(RiskManager.ORB_STOP_PCT * 100),
            "tighten_interval": RiskManager.STOP_TIGHTEN_INTERVAL,
            "tighten_step":     round(RiskManager.STOP_TIGHTEN_STEP * 100),
            "floor_pct":        round(RiskManager.STOP_FLOOR_PCT * 100),
            "stage1_gain":      round(RiskManager.ORB_STAGE1_GAIN * 100),
            "daily_cap":        round(DAILY_LOSS_HARD_CAP_PCT * 100),
            "kill_lock_hours":  _settings.get("kill_lock_hours", KILL_LOCK_HOURS),
            "rr_small":         MIN_RR_RATIO_SMALL_ACCOUNT,
            "rr_pro":           MIN_RR_RATIO_PROFESSIONAL,
            "vol_mult":         _settings.get("volume_filter_multiplier", 2.0),
        }
    except Exception:
        return _defaults


def _technical_tip(exit_reason: str) -> str:
    """
    A second, technical-but-plain-language tip for losing trades.

    Unlike _improvement_tip() (which describes *behavior*), this one names a
    specific dial — a real variable name, what file it lives in, its current
    value, and what turning it up/down would do — so the trade can actually
    be changed. Every term that isn't everyday English is spelled out inline
    (no bare "RVOL", "R:R", etc. without an explanation of what it means).
    Values are read live via _live_risk_constants() — see that function's
    docstring for why this used to drift out of date.
    """
    er = (exit_reason or "").lower()
    k = _live_risk_constants()

    if "time_box_45m" in er:
        return (
            "This trade was force-closed by the bot's 45-minute time limit "
            "(<code>ORB_TIME_BOX</code> in risk.py). There's also a 'how busy "
            "does trading need to be before entering' dial — "
            f"<code>volume_filter_multiplier</code> in config.py, currently "
            f"{k['vol_mult']:g}× the normal level. Raising that number makes "
            "the bot wait for bigger, more obvious moves before it gets in, "
            "which would mean fewer trades that just go nowhere and time out."
        )
    if "dynamic_stop" in er or "structural_stop" in er:
        return (
            "The starting stop-loss distance is <code>ORB_STOP_PCT</code> in "
            f"risk.py — currently {k['stop_pct']}% of the option's price. It "
            f"also shrinks over time: every {k['tighten_interval']} minutes "
            "(<code>STOP_TIGHTEN_INTERVAL</code>) it tightens by "
            f"{k['tighten_step']} percentage points "
            f"(<code>STOP_TIGHTEN_STEP</code>), down to a floor of "
            f"{k['floor_pct']}% (<code>STOP_FLOOR_PCT</code>) — that's why "
            f"the exit reason shows a number that may be less than "
            f"{k['stop_pct']}%. Making <code>ORB_STOP_PCT</code> bigger (or "
            "tightening it more slowly) gives a trade more room to be "
            "'right' before the bot bails, but each loss would also cost "
            "more. There's also a minimum reward-to-risk requirement before "
            "the bot will even take a trade (<code>rr_ratio_mode</code> in "
            f"Settings — currently {k['rr_small']:g}x for small accounts, "
            f"{k['rr_pro']:g}x once the account grows); raising that makes "
            "the bot pickier about which setups it takes."
        )
    if "kill_lock_force_close" in er:
        return (
            "This trade was closed automatically because the account hit "
            "its daily loss limit — <code>DAILY_LOSS_HARD_CAP_PCT</code> in "
            f"config.py, currently {k['daily_cap']}% of the account in one "
            "day — which then pauses new trades for "
            f"{k['kill_lock_hours']} hours (<code>KILL_LOCK_HOURS</code>). "
            f"How much each single loss counts toward that {k['daily_cap']}% "
            "is set by the risk-per-trade percentage (the risk tier in Risk "
            "Settings — up to 5% per trade on small/bootstrap accounts with "
            "growth mode on, 1% otherwise). Lowering that percentage means "
            "each loss is smaller, so it takes more losing trades in a row "
            "to trigger this pause."
        )
    if "stage2_break_even" in er or "stage2_stop_be" in er:
        return (
            "This trade had already hit its first profit target — "
            f"<code>ORB_STAGE1_GAIN</code> in risk.py, currently a "
            f"{k['stage1_gain']}% gain — which locks in part of the "
            "position, before giving the rest back. Lowering "
            "<code>ORB_STAGE1_GAIN</code> would lock in profit sooner "
            "(smaller but more reliable wins); raising it holds out for a "
            "bigger move before banking anything."
        )

    return (
        "The two main dials that affect every trade are <code>ORB_STOP_PCT</code> "
        f"in risk.py (currently {k['stop_pct']}% — how far price can move "
        "against the trade before it's cut) and the risk-per-trade "
        "percentage in Risk Settings (up to 5% per trade on small/bootstrap "
        "accounts with growth mode on, 1% otherwise — how much of the "
        "account each trade risks). Adjusting either changes how big this "
        "kind of loss can get."
    )


# ── Helpers ────────────────────────────────────────────────────────────────────
def _clean_str(value) -> str:
    """Convert None / NaN (float that != itself) to '', otherwise str()."""
    if value is None:
        return ""
    try:
        if value != value:   # NaN check without importing pandas/math
            return ""
    except Exception:
        pass
    return str(value)


# ── Main entry point ──────────────────────────────────────────────────────────
def build_trade_note_html(trade: dict) -> str:
    """
    Build the HTML "Notes" cell content for one trade row.

    Layout:
      <div class="cm-note-tldr">2-line-clamped plain-English TL;DR</div>
      <a href="#cm-note-<id>" class="cm-note-link">📝 Full breakdown</a>
      <div id="cm-note-<id>" class="cm-note-overlay">       <- hidden until
        <div class="cm-note-paper">                            its anchor is
          ✕ Close                                              targeted
          Why it entered / What it noticed / Why it exited /
          (Could do better — red, losses only)
        </div>
      </div>

    The overlay/paper popup requires NOTE_MODAL_CSS to be injected once on
    the page (st.markdown(NOTE_MODAL_CSS, unsafe_allow_html=True)).

    Parameters
    ----------
    trade : dict
        A single trade record (e.g. one row of df_j.to_dict()). Expected keys:
        id, ticker, option_type, strike, strategy_id, exit_reason,
        realized_pnl. Missing or NaN/None values are handled gracefully.

    Returns
    -------
    str
        HTML string safe to drop into _html_table()'s unsafe_allow_html
        rendering.
    """
    try:
        strategy_id = _clean_str(trade.get("strategy_id"))
        option_type = _clean_str(trade.get("option_type")).lower() or "call"
        direction   = "put" if option_type == "put" else "call"
        exit_reason = _clean_str(trade.get("exit_reason"))

        entry = _ENTRY.get(strategy_id, {}).get(direction, {})
        entry_short = entry.get("short", _DEFAULT_ENTRY_SHORT)
        entry_long  = entry.get("long",  _DEFAULT_ENTRY_LONG)
        obs_long    = _OBSERVATIONS.get(strategy_id, _DEFAULT_OBSERVATION)

        # ── Determine outcome for the TL;DR ───────────────────────────────────
        pnl = trade.get("realized_pnl")
        try:
            has_pnl = pnl is not None and pnl == pnl   # not NaN
        except Exception:
            has_pnl = False

        if not exit_reason:
            # Trade still open — short TL;DR, no exit/could-do-better detail.
            tldr = f"Still open — entered on {entry_short}."
            details_body = (
                f"<b>Why it entered:</b> {entry_long}<br>"
                f"<b>What it noticed:</b> {obs_long}<br>"
                f"<b>Why it exited:</b> {_exit_long(exit_reason)}"
            )
        else:
            outcome_word = "a win" if (has_pnl and pnl > 0) else "a loss" if has_pnl else "closed"
            tldr = (f"Entered on {entry_short}, exited {_exit_short(exit_reason)} "
                    f"— {outcome_word}.")
            details_body = (
                f"<b>Why it entered:</b> {entry_long}<br>"
                f"<b>What it noticed:</b> {obs_long}<br>"
                f"<b>Why it exited:</b> {_exit_long(exit_reason)}"
            )
            # "Could do better" only for closed, losing (or break-even) trades.
            if has_pnl and pnl <= 0:
                tip = _improvement_tip(exit_reason)
                tech_tip = _technical_tip(exit_reason)
                details_body += (
                    f"<br><b>Could do better:</b> "
                    f"<span style='color:red'>{tip}</span>"
                    f"<br><b>Could do better (technical):</b> "
                    f"<span style='color:#b35900'>{tech_tip}</span>"
                )

        # ── Unique anchor id for this row's popup ─────────────────────────────
        # Prefer the trade's DB primary key (always unique). Fall back to a
        # hash of a few fields if "id" is somehow missing, so the popup still
        # works (just without a guaranteed-stable anchor across reruns).
        raw_id = trade.get("id")
        try:
            if raw_id is None or raw_id != raw_id:   # None or NaN
                raise ValueError
            anchor_id = f"cm-note-{int(raw_id)}"
        except Exception:
            anchor_id = f"cm-note-{abs(hash((strategy_id, exit_reason, str(trade.get('entry_time', '')))))}"

        # ── Friendly header for the popup (e.g. "AMZN PUT $285") ──────────────
        ticker = _clean_str(trade.get("ticker"))
        try:
            strike_str = f"${float(trade.get('strike')):g}"
        except Exception:
            strike_str = ""
        header_bits = [b for b in (ticker, option_type.upper(), strike_str) if b]
        header = " ".join(header_bits) or "Trade Note"

        return (
            f"<div class='cm-note-tldr'>{tldr}</div>"
            f"<a href='#{anchor_id}' class='cm-note-link'>📝 Full breakdown</a>"
            f"<div id='{anchor_id}' class='cm-note-overlay'>"
            f"<div class='cm-note-paper'>"
            f"<a href='#' class='cm-note-close'>✕ Close</a>"
            f"<h4>📝 {header}</h4>"
            f"{details_body}"
            f"</div>"
            f"</div>"
        )
    except Exception:
        # Never let a malformed trade record break the whole journal table.
        return "<i>Note unavailable.</i>"
