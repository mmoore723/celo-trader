/**
 * Playbooks.tsx — Strategy reference cards.
 * Lightweight read-only reference; interactive replay lives in the Streamlit legacy.
 */

interface Strategy {
  id: string;
  name: string;
  emoji: string;
  setup: string;
  entry: string;
  stop: string;
  target: string;
  notes: string;
  evidence?: string;
  tags: string[];
  tuning: { param: string; value: string }[];
}

const STRATEGIES: Strategy[] = [
  {
    id: "orb",
    name: "Opening Range Breakout",
    emoji: "🎯",
    setup:  "Price forms a tight range during 9:30–9:44 ET. Breakout detected 9:45–10:30; retest entry allowed until 10:45.",
    entry:  "Candle close above ORB high (long) or below ORB low (short). Dynamic RVOL gate (see tuning).",
    stop:   "Below ORB low (long) or above ORB high (short). -50% hard stop on option premium.",
    target: "Stage 1: +50% on premium. Stage 2: ATR trail floor at +15%. Time-box 20 min losing / 90 min after Stage 1.",
    notes:  "Highest-probability signal. Skipped if price > 3× ATR from boundary (overextended). 20-min cooldown per ticker.",
    tags:   ["primary", "momentum"],
    tuning: [
      { param: "Window",          value: "9:45–10:30 detect / 10:45 retest" },
      { param: "RVOL (early)",    value: "≥ 1.0× floor before 10:30" },
      { param: "RVOL (after)",    value: "≥ 0.75× floor after 10:30" },
      { param: "RVOL (MSA conf)", value: "≥ 0.75× (structure confirmed)" },
      { param: "Overext. skip",   value: "> 3.0× ATR from boundary" },
      { param: "Retest tol.",     value: "0.15% of level (min $0.05)" },
      { param: "Cooldown",        value: "20 min per ticker" },
    ],
  },
  {
    id: "vwap",
    name: "VWAP Pullback",
    emoji: "📈",
    setup:  "Trending stock pulls back to VWAP after a strong first push above/below. Needs ≥ 8 bars today.",
    entry:  "Bounce off VWAP with RVOL gate and ≥ 3 of the last 5 bars on correct side of VWAP before the touch.",
    stop:   "Below VWAP (long) or above VWAP (short). -50% hard stop on premium.",
    target: "Stage 1: +50%. Stage 2: ATR trail. Time-box 20 min losing / 90 min after Stage 1.",
    notes:  "Works best when VWAP is flat or slightly sloped, not during chop.",
    tags:   ["secondary", "mean-reversion"],
    tuning: [
      { param: "Window",          value: "9:45 ET onwards (≥ 8 bars)" },
      { param: "RVOL gate",       value: "Dynamic (≥ 1.0× early / ≥ 0.75× after 10:30 / ≥ 0.75× with MSA)" },
      { param: "VWAP side check", value: "≥ 3 of last 5 bars on correct side" },
      { param: "Conf. range",     value: "0.60 – 0.82" },
      { param: "Conf. formula",   value: "0.60 + proximity×0.15 + (RVOL−min, max 1.0)×0.07" },
      { param: "Cooldown",        value: "20 min per ticker" },
    ],
  },
  {
    id: "fvg",
    name: "Fair Value Gap",
    emoji: "⚡",
    setup:  "3-bar pattern: impulse candle leaves a gap between candle 1's high and candle 3's low. Retest of the gap zone.",
    entry:  "First candle that closes into the FVG zone. Gap must be ≥ 0.5× ATR14 wide. RVOL ≥ 1.5×.",
    stop:   "Beyond the 50% midpoint of the FVG zone.",
    target: "Swing high/low that created the FVG move. Stage 1 at +25%, Stage 2 trail.",
    notes:  "Liquidity sweep of a prior swing in the last 15 bars upgrades confidence to 0.90. No sweep caps at 0.78 (near EMA50) or 0.75 (extended).",
    tags:   ["structural", "ICT"],
    tuning: [
      { param: "Window",        value: "9:45 ET onwards (≥ 6 bars)" },
      { param: "RVOL gate",     value: "≥ 1.5× (hard — not dynamic)" },
      { param: "Gap min width", value: "≥ 0.5× ATR14" },
      { param: "Sweep lookback",value: "15 bars" },
      { param: "Conf. (sweep)", value: "0.55 – 0.90  (base + 0.07 sweep bonus)" },
      { param: "Conf. (no swp)",value: "cap 0.78 near EMA50 / 0.75 extended" },
      { param: "Conf. formula", value: "0.55 + min(gap/ATR, 2.0)×0.10 + min(RVOL−1.5, 1.0)×0.05" },
      { param: "Cooldown",      value: "20 min per ticker" },
    ],
  },
  {
    id: "ifvg",
    name: "Inverted Fair Value Gap",
    emoji: "🔄",
    setup:  "FVG zone fully violated (body close through far edge) → zone flips polarity. Entry on retest of the now-inverted zone.",
    entry:  "Retest bar closes back into the inverted zone within 15 bars of the violation. RVOL ≥ 1.5×. Liquidity sweep REQUIRED.",
    stop:   "Candle body close through the opposite edge of the IFVG zone.",
    target: "Next major liquidity level (swing high/low). Stage 1 at +25%, Stage 2 trail.",
    notes:  "Signal direction is OPPOSITE to the original gap: bullish FVG violated → bearish (puts); bearish FVG violated → bullish (calls). Higher win-rate than FVG because zone is proven twice.",
    tags:   ["structural", "ICT", "reversal"],
    tuning: [
      { param: "Window",           value: "9:45 ET onwards (≥ 8 bars)" },
      { param: "Gap lookback",     value: "25 bars for original gap" },
      { param: "Retest window",    value: "≤ 15 bars after violation" },
      { param: "RVOL gate",        value: "≥ 1.5× on retest bar" },
      { param: "Sweep",            value: "REQUIRED (hard block — not optional)" },
      { param: "Gap min width",    value: "≥ 0.5× ATR14" },
      { param: "VWAP",             value: "Soft gate — conflict deducts 0.05 confidence" },
      { param: "Conf. range",      value: "0.55 – 0.88" },
      { param: "Conf. formula",    value: "0.60 + min(gap/ATR,2.0)×0.08 + min(RVOL−1.5,1.0)×0.05 − 0.05 if VWAP conflict" },
    ],
  },
  {
    id: "bos",
    name: "BOS / MSS",
    emoji: "🔓",
    setup:  "Break of Structure: price takes out a prior swing high (bullish) or swing low (bearish). Requires FVG evidence within last 20 bars.",
    entry:  "BOS candle close. RVOL ≥ 1.5× hard floor. Skipped if already > 1.5× ATR past the break level.",
    stop:   "Below last higher low (bullish) or above last lower high (bearish). -50% hard stop on premium.",
    target: "Next significant swing level. Stage 1 +50%, Stage 2 ATR trail.",
    notes:  "MSS (Market Structure Shift) is the strongest signal — trend reversal. Needs ≥ 10 bars before it's eligible.",
    tags:   ["structural", "smc"],
    tuning: [
      { param: "Min bars",       value: "≥ 10 bars today" },
      { param: "RVOL floor",     value: "≥ 1.5× (hard floor, not dynamic)" },
      { param: "Overext. skip",  value: "> 1.5× ATR past swing level" },
      { param: "FVG confirm",    value: "Within last 20 bars" },
      { param: "Cooldown",       value: "20 min per ticker" },
    ],
  },
  {
    id: "flip",
    name: "Flip Trading",
    emoji: "🔄",
    setup:  "Bot has an open directional trade that fails and price reverses through the original trigger level.",
    entry:  "Auto-flips CALL→PUT or PUT→CALL when reversal is confirmed at the ORB boundary.",
    stop:   "Mirror of original — now the opposite ORB level. -50% hard stop on premium.",
    target: "Same two-stage exit: Stage 1 +50%, Stage 2 ATR trail.",
    notes:  "Enabled/disabled in Settings. Adds churn risk — keep off if RVOL is low.",
    tags:   ["adaptive", "risk"],
    tuning: [
      { param: "Trigger",    value: "Price crosses ORB boundary opposite to entry" },
      { param: "Stop",       value: "Opposite ORB level" },
      { param: "Enable/off", value: "flip_trading_enabled in Settings" },
    ],
  },
  {
    id: "chan",
    name: "Channel Breakout",
    emoji: "🏹",
    setup:  "Price is range-bound for ≥ 4 bars. Identify horizontal resistance/support.",
    entry:  "Breakout candle closes above resistance (long) or below support (short). Dynamic RVOL ≥ 1.0×.",
    stop:   "Back inside the channel.",
    target: "Channel height projected from breakout point.",
    notes:  "⚠️ Currently DISABLED. Avoid in the first 15 minutes (ORB window) and last 20 minutes of session.",
    tags:   ["breakout", "range"],
    tuning: [
      { param: "Status",       value: "⚠️ DISABLED in router + backtester" },
      { param: "RVOL gate",    value: "≥ 1.0× (relaxed vs. other strategies)" },
      { param: "Min range",    value: "≥ 4 bars of consolidation" },
      { param: "Cooldown",     value: "20 min per ticker" },
    ],
  },
  {
    id: "mid",
    name: "Mid-Day Breakdown",
    emoji: "📉",
    setup:  "10:30–13:00 ET only. Price collapses below OR Low with VWAP as resistance. MSA must confirm a Lower High.",
    entry:  "Enter PUT: price closes below OR Low AND below VWAP AND MSA Lower High confirmed. Dynamic RVOL gate.",
    stop:   "Above OR Low. If price reclaims it, setup is invalid. -50% hard stop on premium.",
    target: "Stage 1: +50% below entry. Stage 2: trail to next swing low. Time-box 20 min losing / 90 min after Stage 1.",
    notes:  "Bearish-only. Window strictly 10:30–13:00 ET. With MSA confirmed the RVOL floor relaxes to 0.75×.",
    tags:   ["secondary", "bearish"],
    tuning: [
      { param: "Window",          value: "10:30–13:00 ET (bearish only)" },
      { param: "RVOL gate",       value: "Dynamic; 0.75× with MSA confirmed" },
      { param: "Conf. range",     value: "0.65 – 0.86" },
      { param: "Conf. formula",   value: "0.65 + min(RVOL−1.0, 2.0)×0.04 + 0.05 if downtrend" },
      { param: "Cooldown",        value: "20 min per ticker" },
    ],
  },
  {
    id: "trend",
    name: "Trend Continuation",
    emoji: "🌊",
    setup:  "Established trend (Higher Low for uptrends, Lower High for downtrends). This is the 2nd or 3rd entry — trend must already be proven.",
    entry:  "Bullish: close above Higher Low bar with RVOL ≥ 1.2× and price above VWAP. Bearish: inverse. Pivot must be ≤ 20 bars old.",
    stop:   "Below the Higher Low (bullish) or above the Lower High (bearish).",
    target: "Previous swing high/low. Stage 1 +50%, Stage 2 ATR trail.",
    notes:  "Lowest RVOL threshold (1.2×) because the trend does the heavy lifting. Active 9:45–14:30 ET.",
    tags:   ["secondary", "momentum"],
    tuning: [
      { param: "Window",        value: "9:45–14:30 ET" },
      { param: "RVOL min",      value: "≥ 1.2× (lowest of all strategies)" },
      { param: "Pivot max age", value: "≤ 20 bars (stale pivots skipped)" },
      { param: "Conf. range",   value: "0.65 – 0.82" },
      { param: "Conf. formula", value: "0.65 + min((RVOL−1.2)×0.06, 0.08) + depth bonus" },
      { param: "Cooldown",      value: "20 min per ticker" },
    ],
  },
];

// ── Global risk / exit parameters (shared across all strategies) ─────────────
const GLOBAL_PARAMS: { param: string; value: string; note?: string }[] = [
  // ── Entry / sizing ──────────────────────────────────────────────────────────
  { param: "Min R:R (bootstrap)", value: "1.2× (balance < $5k)" },
  { param: "Min R:R (standard)",  value: "1.6×" },
  { param: "Max positions",       value: "2 concurrent" },
  { param: "Spread max",          value: "$0.10 bid-ask" },
  { param: "RVOL baseline",       value: "5-min bars, 10-day same-slot avg" },
  // ── Exit hierarchy ──────────────────────────────────────────────────────────
  { param: "Stage 1 target",      value: "+50% on option premium",   note: "Exits 50% of contracts" },
  { param: "Stage 2 trail lock",  value: "+15% profit floor",         note: "Floor locked after Stage 1" },
  { param: "Hard stop",           value: "−50% on option premium" },
  { param: "Momentum stop",       value: "−20% early exit",           note: "Only first 20 min if losing" },
  { param: "Time-box (losing)",   value: "60 min max" },
  { param: "Time-box (winner)",   value: "90 min after Stage 1" },
  { param: "ATR trail warmup",    value: "5 min + option ≥ +15%",     note: "Trail doesn't arm before both gates" },
  // ── Multi-timeframe ATR trail (dynamic) ────────────────────────────────────
  { param: "ATR source",          value: "5-min bars (falls back to 1-min)",  note: "Less noisy than 1-min" },
  { param: "Trail mult — base",   value: "2.0× ATR",                  note: "Default when 1h trend is neutral" },
  { param: "Trail mult — 1h with",value: "2.5× ATR",                  note: "1-hour EMA20 aligned with trade → give runners room" },
  { param: "Trail mult — 1h vs.", value: "1.5× ATR",                  note: "1-hour EMA20 opposing trade → tighter stop" },
  { param: "Trail mult — exhaust",value: "1.0× ATR",                  note: "5-min RSI >72 (call) or <28 (put) → very tight" },
  { param: "Trail mult — MACD",   value: "≤ 1.5× ATR",               note: "5-min MACD hist declining 2 bars → fade signal" },
  { param: "Trail mult — 15m lvl",value: "1.0× ATR",                  note: "Within 0.3% of 15-min swing level → near wall" },
  // ── VWAP breach (trend-dead gate) ──────────────────────────────────────────
  { param: "VWAP breach (5-min)", value: "2 consecutive 5-min bars",  note: "Primary signal when 5m data loaded" },
  { param: "VWAP breach (1-min)", value: "5 consecutive 1-min bars",  note: "Fallback if 5-min not yet loaded" },
  { param: "Trend-dead confirm",  value: "ADX < 20 AND EMA stack broken", note: "Both required — prevents false exits on dips" },
  // ── Risk controls ──────────────────────────────────────────────────────────
  { param: "Kill lock",           value: "24 hrs after daily cap" },
];

const TAG_COLORS: Record<string, string> = {
  primary:       "badge-blue",
  secondary:     "badge-yellow",
  momentum:      "badge-green",
  structural:    "badge-blue",
  ICT:           "badge-blue",
  smc:           "badge-blue",
  adaptive:      "badge-yellow",
  risk:          "badge-red",
  breakout:      "badge-green",
  "mean-reversion": "badge-yellow",
  range:         "badge-yellow",
  bearish:       "badge-red",
};

// ── Log event code explanations ───────────────────────────────────────────
const LOG_CODES: { code: string; plain: string; detail: string; tag: string }[] = [
  // ── System events ─────────────────────────────────────────────────────
  { code: "logging_initialised",   tag: "system",  plain: "Bot started up",
    detail: "The bot just launched and its logging system is ready. Next step: scan for today's watchlist." },
  { code: "balance_update",        tag: "system",  plain: "Account balance refreshed",
    detail: "The bot fetched the latest account balance from Alpaca. Used to size every trade correctly." },
  { code: "network_error",         tag: "system",  plain: "API connection problem",
    detail: "The broker API returned an error or timed out. Bot will retry automatically on the next tick." },
  { code: "reconnecting",          tag: "system",  plain: "Lost connection — trying to reconnect",
    detail: "WebSocket or API link dropped. Bot pauses new entries until the connection is restored." },

  // ── Scanning / thinking ───────────────────────────────────────────────
  { code: "bar_eval",              tag: "think",   plain: "Per-candle bot narration",
    detail: "Fires once per closed 1-minute candle. Shows exactly what the bot is watching: price vs. the Opening Range, volume level (RVOL), VWAP alignment, which gates pass/fail, and what would need to change for a trade to trigger. When a position is open, shows live P&L, stop cushion, Stage 1 distance, and time-box countdown instead." },
  { code: "bar_evaluation",        tag: "think",   plain: "Per-candle strategy check (legacy label)",
    detail: "Older label for the same per-candle evaluation. See bar_eval for the current format." },
  { code: "scan_complete",         tag: "think",   plain: "Pre-market scan finished",
    detail: "The bot scanned 9:00–9:25 ET for the top RVOL/momentum candidates. These become today's watchlist." },

  // ── Gate checks ──────────────────────────────────────────────────────
  { code: "RVOL_gate_pass",        tag: "gate",    plain: "Volume check passed ✅",
    detail: "Relative volume (today vs. 10-day average at this time of day) is ≥ 1.5×. Elevated volume means the move is more likely real and not a fake-out." },
  { code: "RVOL_gate_fail",        tag: "gate",    plain: "Volume too low — skipping ❌",
    detail: "RVOL is below the 1.5× threshold. Low volume breakouts fail ~70% of the time. Bot waits for more participation before entering." },
  { code: "rr_gate_pass",          tag: "gate",    plain: "Risk:Reward ratio is acceptable ✅",
    detail: "The distance to the target is at least the minimum multiple of the distance to the stop. A good R:R means the math works even if you're right less than half the time." },
  { code: "rr_gate_fail",          tag: "gate",    plain: "Risk:Reward too poor — skipping ❌",
    detail: "At current prices, the potential gain doesn't justify the risk. Common when premiums are inflated or the stop is too far away." },
  { code: "spread_gate_fail",      tag: "gate",    plain: "Bid-ask spread too wide ❌",
    detail: "The gap between the option's buy price and sell price exceeds 10%. A wide spread means you instantly lose money the moment you enter. Bot skips." },
  { code: "orb_already_triggered", tag: "gate",    plain: "ORB already used on this ticker today",
    detail: "The bot only takes one Opening Range Breakout trade per ticker per session. This prevents chasing the same ticker repeatedly if it fails and re-tests." },
  { code: "vwap_gate_fail",        tag: "gate",    plain: "VWAP alignment missing — skipping ❌",
    detail: "For a CALL, price must be above VWAP (market buying pressure). For a PUT, below VWAP. Without this, you'd be fighting the macro trend." },
  { code: "struct_stop_set",       tag: "gate",    plain: "Structural stop level established",
    detail: "A key price level (swing low for longs, swing high for shorts) was identified as the hard stop anchor. If price closes below/above this, the setup is broken." },

  // ── Trade signals & entries ───────────────────────────────────────────
  { code: "Trade_Signal",          tag: "signal",  plain: "Valid trade setup — all gates passed 🔥",
    detail: "Every required condition is met: RVOL ≥ threshold, VWAP aligned, R:R acceptable, spread OK, ORB/strategy trigger confirmed. The bot is about to submit an order." },
  { code: "entry_placed",          tag: "order",   plain: "Order submitted to broker",
    detail: "The option buy order was sent to Alpaca. The bot is now waiting for a fill confirmation. If the fill doesn't come back, it cancels to avoid orphaned orders." },
  { code: "entry_filled",          tag: "order",   plain: "Order filled — position is live ✅",
    detail: "Broker confirmed the trade executed at the listed price. Stop and Stage 1 target are now set. Time-box countdown begins." },
  { code: "entry_rejected",        tag: "order",   plain: "Order rejected by broker",
    detail: "Alpaca rejected the order — usually insufficient buying power or an invalid contract. The rejection reason is logged. No position opened." },
  { code: "flip_trade",            tag: "signal",  plain: "Bot flipped direction on a reversal 🔄",
    detail: "A trade failed and price reversed strongly through the original trigger level. The bot auto-flipped from CALL→PUT (or PUT→CALL) to ride the new direction. Only fires if flip trading is enabled in Settings." },

  // ── Position management ───────────────────────────────────────────────
  { code: "position_narration",    tag: "think",   plain: "Live position status update",
    detail: "Emitted every minute while in a trade. Shows: current option price vs. entry, unrealized P&L in $ and %, cushion above the stop, distance to Stage 1 target, time-box countdown, and whether momentum (RVOL) is holding." },
  { code: "stop_tightened",        tag: "risk",    plain: "Stop moved up to protect profits",
    detail: "After Stage 1 hit or a strong momentum move, the stop was raised toward breakeven or above. This locks in gains even if the trade reverses." },
  { code: "trailing_stop_update",  tag: "risk",    plain: "Trailing stop adjusted",
    detail: "As price moved in our favor, the stop followed it upward (for longs) keeping pace with the move. This is how runners ride big moves while protecting gains." },

  // ── Exits ─────────────────────────────────────────────────────────────
  { code: "stage1_exit",           tag: "exit",    plain: "Took first-half profit (Stage 1) 🎯",
    detail: "Price hit the Stage 1 target (~50–100% gain on the option). Half the contracts were sold to lock in profit. Remaining contracts run with a tighter trailing stop toward Stage 2." },
  { code: "stage2_exit",           tag: "exit",    plain: "Closed remaining position (Stage 2)",
    detail: "The trailing stop or time-box triggered on the remaining contracts. Full position is now flat." },
  { code: "stop_hit",              tag: "exit",    plain: "Stop loss triggered — position closed 🔴",
    detail: "Price hit the pre-set stop level. The position was closed to limit the loss. This is normal risk management — not every trade wins. Loss was limited to the pre-calculated amount." },
  { code: "time_box_exit",         tag: "exit",    plain: "Time-box expired — trade closed ⏱️",
    detail: "The trade ran out of time: 45 minutes (or 90 min if Stage 1 was already hit). Position closed regardless of P&L. Time-boxes prevent overnight holds and slow bleeders." },
  { code: "manual_close",          tag: "exit",    plain: "Trade manually closed by user",
    detail: "You clicked the Close button in the Trade Journal or Live Trading page. Position was closed at market." },
  { code: "panic_close",           tag: "exit",    plain: "Panic Close — all positions closed 🚨",
    detail: "Panic Close was triggered. All open option positions were closed at market immediately." },

  // ── Risk controls ─────────────────────────────────────────────────────
  { code: "kill_lock_active",      tag: "risk",    plain: "Daily loss limit hit — bot locked 🔒",
    detail: "Total realized losses for the session hit the maximum allowed. Bot stops placing new trades until the next trading day. Existing positions are still managed." },
  { code: "ghost_position_detected",tag:"risk",    plain: "Open position found without a DB record",
    detail: "Alpaca shows an open option position that isn't in the bot's trade journal. Could be a leftover from a crash or manual trade. Bot flags it for review — it won't manage a ghost position automatically." },
  { code: "affordability_block",   tag: "risk",    plain: "Premium too expensive for current buying power",
    detail: "The cheapest contract for this signal costs more than the account's options buying power allows. Bot skips rather than over-leveraging." },
];

const TAG_BADGE: Record<string, string> = {
  system: "badge-blue",
  signal: "badge-green",
  order:  "badge-blue",
  exit:   "badge-red",
  think:  "badge-yellow",
  gate:   "badge-yellow",
  risk:   "badge-red",
  // aliases used in newer log entries
  orders: "badge-blue",
  exits:  "badge-red",
};

import { useState, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { Search, ChevronDown, ChevronRight } from "lucide-react";
import { StrategyPlaybookExperience } from "../components/playbooks/StrategyPlaybookExperience";
import { Tooltip } from "../components/Tooltip";
import { GLOSSARY } from "../lib/glossary";
import { api } from "../lib/api";

// ── How It Works — comprehensive bot explainer ────────────────────────────────
const HOW_IT_WORKS: { id: string; emoji: string; title: string; body: string[] }[] = [
  {
    id: "routine",
    emoji: "🕐",
    title: "The Trading Day — Step by Step",
    body: [
      "8:00 AM ET — Bot wakes up, fetches your Alpaca account balance, and updates internal risk sizing.",
      "9:00–9:25 AM ET — Pre-market scan: checks ~140 liquid US stocks and ETFs for gap + volume. Tickers with a 1–4% gap AND elevated relative volume (RVOL ≥ 2×) make the cut. Top 10 become today's watchlist.",
      "9:30 AM ET — Market opens. SPY and QQQ are always added as anchors regardless of gap. Any tickers you pinned in Settings > Watchlist are prepended so the bot always watches them.",
      "9:45 AM ET — Strategy evaluation begins. Before 9:45 the opening range is still forming — entering too early means fighting the noise. INST_ORB, VWAP Pullback, FVG, IFVG, and Trend Continuation all activate here.",
      "10:30 AM ET — Mid-Day Breakdown activates (bearish-only, runs until 1:00 PM).",
      "1:00 PM ET — Afternoon Reversal activates (runs until 3:30 PM).",
      "2:30 PM ET — Trend Continuation closes its entry window. No new trend-cont entries after this.",
      "3:55 PM ET — Hard session cutoff. All remaining positions are closed regardless of P&L. Options expire and after-hours liquidity evaporates — this is non-negotiable.",
      "After 4:00 PM ET — Bot enters deep sleep. No API calls, no evaluation. Wakes at 8:00 AM next trading day.",
    ],
  },
  {
    id: "scanner",
    emoji: "🔍",
    title: "How the Watchlist Gets Built",
    body: [
      "The scanner runs daily_premarket_scan() once per session, at or after 9:30 ET. It pulls a snapshot of every ticker in the LIQUID_POOL (~140 stocks and ETFs) from Alpaca in one batch.",
      "Filter 1 — Price: stock must trade above $10. Sub-$10 names have thin options chains and erratic gaps.",
      "Filter 2 — Gap: the open price must be 1–4% away from yesterday's close (either direction). Below 1% = no real move. Above 4% = already overextended before the bell. ETFs get a lower floor of 0.5% because even a 0.5% gap on SPY is a real institutional move.",
      "Filter 3 — Volume: average daily volume over 20 days must exceed 2 million shares. Low-volume names have wide options spreads and fake breakouts.",
      "Filter 4 — ATR: the 14-day Average True Range must exceed $1. This ensures the stock actually moves enough for the option premium to be meaningful.",
      "Filter 5 — RVOL: relative volume (today's shares so far vs. historical same-time average) must be ≥ 2× for stocks, ≥ 1.5× for ETFs. Elevated volume means institutions are involved — the move is more likely real.",
      "Scoring: survivors are ranked by RVOL × gap size × ATR factor × liquidity bonus. ETFs get a 1.15× liquidity bonus because their options chains are deeper and spreads tighter.",
      "Affordability check: the scanner also estimates whether options on a ticker would actually fit your risk budget. If the estimated stop-loss on 1 contract (option premium × 30%) exceeds your risk budget, the ticker is heavily de-ranked — it would just be skipped every tick anyway.",
      "The top 10 survivors become today's watchlist. SPY and QQQ are always added as anchors. Your pinned Settings tickers are prepended to the front so they're always evaluated.",
    ],
  },
  {
    id: "tick",
    emoji: "⏱️",
    title: "How the Bot Evaluates Tickers",
    body: [
      "Every minute the bot evaluates ALL watchlist tickers in one pass — this is the 'batch tick' approach. Old design evaluated one ticker every 10 seconds, which meant a 10-ticker watchlist took ~100 seconds to cycle through and some bars were missed entirely.",
      "For each ticker in the pass, the bot: (1) fetches today's 1-minute bars from Alpaca, (2) augments with 15 days of 5-minute historical bars for accurate RVOL calculation, (3) runs all enabled strategies, (4) checks all entry gates, (5) selects a contract and places an order if everything passes.",
      "After processing all tickers, the bot sleeps to the next 60-second bar boundary. This ensures every evaluation sees a fresh closed bar rather than re-checking the same partial bar twice.",
      "The Bot Thinking log on the Live Trading page shows one entry per bar per ticker — you can see exactly what the bot considered and why it decided not to trade.",
      "The eval log (Bot Focus panel) records both trades that fired AND tickers that were rejected — with the specific reason: no_signal, below_confidence, zero_contracts, spread_too_wide, or rr_too_low.",
    ],
  },
  {
    id: "signals",
    emoji: "📡",
    title: "How Strategies Generate Signals",
    body: [
      "Every tick, strategy_router.py runs all enabled strategies against today's 1-minute bars and returns a ranked list of signals. The highest-confidence signal wins.",
      "INST_ORB (9:45–10:30): The opening range is the high and low of the first 15 minutes. A breakout above the high = bullish signal (buy calls); below the low = bearish (buy puts). The bot also allows retests of the boundary until 10:45.",
      "VWAP Pullback (all day): VWAP is the volume-weighted average price — the 'fair price' institutions use as a benchmark. When price trends away from VWAP then pulls back to touch it with slowing momentum, a bounce is likely.",
      "FVG — Fair Value Gap (all day): A 3-bar impulse candle leaves a gap between bar 1's high and bar 3's low. Price often comes back to 'fill' the gap. The bot enters on the first candle that closes into the gap zone.",
      "IFVG — Inverted FVG (all day): An existing FVG zone is violated (price closes through it). The zone flips polarity — what was support becomes resistance, or vice versa. Entry on the retest of the inverted zone. Requires a prior liquidity sweep.",
      "MID_BRK — Mid-Day Breakdown (10:30–1:00 PM): Price collapses below the opening range low WITH VWAP acting as resistance. Bearish-only. Requires a confirmed Lower High in market structure. It is currently on a research hold: changing its session, RVOL ceiling, and ADX filter has not produced a profitable edge. It must pass a whole-portfolio holdout before the bot uses it again.",
      "AFT_REV — Afternoon Reversal (1:00–3:30 PM): Price reaches a prior swing high or low from earlier in the session and shows reversal momentum. The morning move exhausts and the afternoon fades it.",
      "TREND_CONT — Trend Continuation (9:45–2:30 PM): An established trend (3+ bars showing Higher Lows for uptrend) is making its second or third entry point. Lower RVOL threshold (1.2×) because the trend does the heavy lifting.",
      "GAP_GO — Gap and Go (9:30–9:45 AM): trades the continuation of a pre-market gap right after the open. A stock gapping up or down isn't enough on its own — price also has to push PAST its own opening bar's high (up-gaps) or low (down-gaps) in the same direction, proving the gap is being defended, not immediately faded. If it fades back through the open instead, no trade.",
      "LIQ_SWEEP — Liquidity Sweep Reversal (9:45 AM–3:30 PM): fades a failed breakout instead of trading a real one. When a wick pierces a recent swing high/low but the candle CLOSES back on the other side of that level, that's read as a stop-hunt/trap — the bot trades the reversal, opposite the direction of the wick.",
      "Each strategy scores signals 0–1 based on quality factors: RVOL level, proximity to key level, gap size vs. ATR, and market structure confirmation. The router applies a conflict veto — if the top two signals disagree on direction by less than 0.05 confidence points, both are rejected as ambiguous.",
    ],
  },
  {
    id: "contracts",
    emoji: "📄",
    title: "Choosing the Option Contract",
    body: [
      "Once a signal fires, the bot calls Tradier's API to fetch the option chain for the signaled ticker and direction (call or put).",
      "Expiry: picks from expirations 7–21 days out (up to the 3 nearest in that window). Wide enough to avoid 0DTE's worst gamma/theta cliff, still short enough to stay cheap.",
      "Strike: picks the first strike OTM from the current stock price (just out-of-the-money, not exactly at it).",
      "Cost filter: option ask price must be between $0.80 and $10.00. Below $0.80 = spread-death on a near-worthless contract; above $10 caps position cost for a small account.",
      "Spread filter (updated 2026-07-31): bid-ask spread must be ≤ 15% of the contract's own ask price (floored at $0.15, capped at $0.50). A flat $0.50 cap used to let a spread eat 62% of a cheap $0.80 contract's premium — now it scales with the contract's own price.",
      "Open interest filter: must have ≥ 150 contracts of open interest. Below this the market is illiquid — your own order could move the price.",
      "After all filters, the cheapest qualifying contract is selected. The ask price is recorded, and a 5% slippage buffer is added to compute the 'effective entry' used for all risk calculations.",
    ],
  },
  {
    id: "sizing",
    emoji: "⚖️",
    title: "How Risk Sizing Works",
    body: [
      "The bot uses a percentage-of-account risk model. Every trade risks a fixed % of your balance, not a fixed dollar amount — this automatically scales position size as your account grows or shrinks.",
      "Bootstrap tier (Growth Mode ON + balance < $5k): 5% per trade. Notional cap: 45% of balance. This tier exists because at sub-$5k, risking 1% per trade would give you a budget so small you could never size even 1 contract on most setups.",
      "Growth tier (balance $5k–$25k): 3% per trade. Notional cap: 30% of balance.",
      "Transition tier (balance $25k–$50k): 2% per trade. Notional cap: 30% of balance.",
      "Conservative tier (Growth Mode OFF or balance > $50k): 1% per trade. Notional cap: 20% of balance.",
      "You can override the automatic tier by setting Risk % in Settings. Your percentage is saved and used directly — it overrides the tier system entirely.",
      "Contract calculation: risk budget = balance × risk_pct. Risk per contract = option premium × 5% slippage factor × 30% stop × 100 shares. Contracts = floor(risk_budget / risk_per_contract). Minimum 1 contract (if premium is affordable at all), maximum capped by notional limit.",
      "Bootstrap floor: if the calculation gives 1 contract but 2 contracts would still fit within the 45% notional cap, the bot floors at 2. This is the '2c vs 1c' behavior — deliberate for small accounts.",
    ],
  },
  {
    id: "gates",
    emoji: "🚦",
    title: "All the Gates Before an Entry",
    body: [
      "The bot runs a checklist before every order. If any gate fails, the ticker is skipped for that bar and re-evaluated next minute.",
      "1. Earnings blackout: if the company reports earnings within the next 2 days, skip it. Options pricing goes wild around earnings — it's speculation, not setup trading.",
      "2. Concurrent position guard: maximum 2 open positions at once, and never 2 positions on the same ticker. This prevents doubling down on a failing trade.",
      "3. Post-win cooldown: 10-minute pause after a profitable close on the same ticker. Prevents the classic mistake of winning then immediately re-entering and giving the profit back.",
      "4. Post-loss displacement: after a losing trade, price must move ≥ 0.3% from the exit level before re-entering. The failed setup must resolve before entering again.",
      "5. Strategy confidence: signal must score above 0.55 (absolute floor from entry.py) and the router pre-filters below 0.74. Low-confidence signals are noise.",
      "6. SPY VWAP macro gate: if SPY trades below its VWAP (bearish macro), any bullish signals on individual tickers are flipped to bearish (puts instead of calls), and vice versa. You're always trading with the broad market.",
      "7. Contract sizing: must be able to afford at least 1 contract within the risk budget. If the option premium implies a stop loss larger than the risk budget, 0 contracts are returned and the ticker is skipped.",
      "8. Spread gate: the bid-ask spread as a % of mid price must be below the spread_gate_pct setting (default 8%). Wide spreads are an immediate performance drag.",
      "9. R:R gate: the potential reward (Stage 1 target) must be ≥ 1.2× the risk (stop loss) for bootstrap accounts, or ≥ 1.6× for standard accounts. The math must work even if you're only right half the time.",
      "10. Duplicate-order guard: can't place the same contract twice in the same minute. Prevents accidental double entries.",
    ],
  },
  {
    id: "management",
    emoji: "📊",
    title: "How Open Trades Are Managed",
    body: [
      "Once a position is open, the bot checks it every minute using position_manager.py. It never ignores an open trade.",
      "Hard stop (−50%): if the option drops 50% from the entry price, the entire position is closed immediately. This is the absolute loss limit per trade.",
      "Stage 1 target (+50%+): if the option gains 50% or more over entry, half the contracts are sold to lock in profit. The remaining contracts continue with a tighter stop.",
      "ATR trail: after Stage 1 hits AND 5 minutes have passed AND the option is up ≥ 15%, a trailing stop activates. The trail uses the Average True Range of 5-minute bars to set a dynamic floor.",
      "Trail multiplier is dynamic — it tightens automatically when: RSI is overbought (>72 calls, <28 puts), MACD momentum is fading, price is near a 15-minute swing level, or the 1-hour EMA opposes the trade direction.",
      "Momentum dead exit: if RVOL drops below 0.7× AND the position is losing, the bot exits early rather than holding a fading trade. Dead volume = dead momentum.",
      "VWAP breach exit: if price closes below VWAP for 2 consecutive 5-minute bars (for a long trade), the trend is likely dead. Position closes before the full stop is hit.",
      "Time-box (losing): if 60 minutes pass without hitting Stage 1, the position closes. Slow bleeders are just as damaging as fast stops.",
      "Time-box (after Stage 1): if 90 minutes pass after Stage 1 and the trail hasn't triggered, the remaining contracts close. Runners have a limit.",
      "Hard session cutoff (3:55 PM): all positions close regardless of status. No exceptions.",
    ],
  },
  {
    id: "exits",
    emoji: "🏁",
    title: "The Exit Priority Order",
    body: [
      "When multiple exit conditions could trigger in the same bar, they're checked in strict priority order:",
      "1st — Hard session cutoff (3:55 PM ET): always fires first if the time is past this threshold. Options lose liquidity fast after 4 PM and this is non-negotiable.",
      "2nd — Kill lock (daily loss limit reached): if total session losses hit the maximum, all positions close and no new trades are allowed for 24 hours.",
      "3rd — Hard stop (−50% on premium): immediate full close. No partial exits, no waiting.",
      "4th — Stage 1 target (+50%+ on premium): sell half the contracts. The other half continues.",
      "5th — ATR trail stop: only active after Stage 1 + 5-minute warmup + option up ≥ 15%. Triggers if price drops back through the trailing floor.",
      "6th — Stage 2 time-box (90 min after Stage 1): closes remaining contracts if trail hasn't triggered.",
      "7th — Momentum dead exit (RVOL < 0.7× while losing): early exit on dead volume.",
      "8th — Losing time-box (60 min without Stage 1): closes the whole position if it was never profitable.",
      "In signal-only mode, the bot computes all of the above but never places or closes orders — it logs what it would do so you can trade manually.",
    ],
  },
  {
    id: "risk",
    emoji: "🛡️",
    title: "Account-Level Risk Safeguards",
    body: [
      "Daily loss limit (Kill Lock): if total realized losses for the session exceed the configured maximum, the bot stops placing new trades for 24 hours. All existing positions are still managed normally. The kill lock resets automatically at the start of the next trading day.",
      "Max concurrent positions: hard cap of 2 open trades at once. Never two positions on the same underlying — that's concentrated risk, not diversification.",
      "Signal-Only Mode: when enabled in Settings, the bot runs its full evaluation pipeline but never places or closes orders. All signals, sizing decisions, and exit triggers are logged exactly as they would fire — you just execute them manually. Useful for understanding bot behavior before going live.",
      "Ghost position detection: if Alpaca shows an open option position that isn't in the bot's trade journal (leftover from a crash or a manual trade), the bot flags it on startup. It won't manage ghost positions automatically — you decide what to do with them.",
      "Per-user isolation: each user account has its own settings.json and trade history. Changing risk settings as one user doesn't affect another user's bot.",
    ],
  },
];

// Category order + display names for the log guide
const LOG_CATEGORIES: { key: string; label: string; emoji: string }[] = [
  { key: "system",  label: "System",             emoji: "⚙️" },
  { key: "think",   label: "Thinking / Scanning", emoji: "🧠" },
  { key: "gate",    label: "Gate Checks",          emoji: "🚦" },
  { key: "signal",  label: "Trade Signals",        emoji: "🔥" },
  { key: "order",   label: "Order Lifecycle",      emoji: "📋" },
  { key: "risk",    label: "Risk Controls",        emoji: "🛡️" },
  { key: "exit",    label: "Exits",                emoji: "🏁" },
];

// Only these current V2 paper pilots belong in the learner's Playbook.  The
// legacy reference data above remains for historic log wording, not lessons.
const CURRENT_STRATEGIES: Strategy[] = [
  {
    id: "v2_orb", name: "TSLA Opening-Range Pullback V2", emoji: "🎯",
    setup: "Mark the first 15 minutes. Wait for price to break the range, then return and test that same level.",
    entry: "A completed 5-minute candle must reclaim the broken level, beat the prior candle, and sit on the correct side of VWAP.",
    stop: "The pullback high or low is the line that proves the idea wrong.",
    target: "Paper study measures a 90-minute option result. The exit stays paper-only while evidence grows.",
    notes: "TSLA only. This is the current interactive lesson because it has the clearest paid option-quote evidence.",
    evidence: "What we know: the unchanged pullback rule was positive in 12 later dates that were not used to choose it. That is promising, not a profit guarantee; it remains paper-only.",
    tags: ["paper", "opening", "pullback"],
    tuning: [{ param: "When", value: "Break before 10:30 ET; confirmation by 10:45 ET" }, { param: "Chop defense", value: "Close + reclaim + VWAP alignment" }],
  },
  {
    id: "v2_trend", name: "SPY Trend Continuation V2", emoji: "🌊",
    setup: "A fast trend is above or below a slower trend, then price closes through its recent range in that same direction.",
    entry: "The completed 5-minute signal fills on the next bar. It never uses a future candle to decide.",
    stop: "An ATR-based invalidation sits beyond the entry candle structure.",
    target: "The current paid option study compares a 90-minute ask-entry/bid-exit result.",
    notes: "SPY only. It evaluates completed five-minute candles and becomes eligible on the following one-minute bar.",
    evidence: "What we know: this is the reviewed SPY paid-quote 30-minute rule. The lesson uses a simplified chart so the trend structure is easier to see.",
    tags: ["paper", "trend", "research"],
    tuning: [{ param: "Chart", value: "5-minute TSLA bars" }, { param: "Evidence", value: "Paid option context study in progress" }],
  },
  {
    id: "v2_spy_fvg", name: "SPY Afternoon Fair Value Gap V2", emoji: "⚡",
    setup: "Between 1:30 and 3:00 PM ET, a three-candle move leaves a meaningful price gap in the direction of the 5-minute trend.",
    entry: "Price returns to that gap for the first time, overlaps it, closes on the favorable half, and stays aligned with VWAP plus EMA trend. Entry is on the following one-minute option quote.",
    stop: "The confirming retest candle’s invalidation level; account-wide protections still apply.",
    target: "The reviewed study exits the same selected contract 30 minutes after entry using the observed bid.",
    notes: "SPY only. This is a narrow afternoon first-retest rule, not the old all-day generic FVG strategy.",
    evidence: "The selected afternoon context was positive in both the earlier and later paid option-quote periods: 25 measured signals overall, with a +3.30% average option markout.",
    tags: ["paper", "afternoon", "gap"],
    tuning: [{ param: "Window", value: "1:30–3:00 PM ET" }, { param: "Gap", value: "≥ 0.5 × ATR on completed 5-minute bars" }, { param: "Trend", value: "EMA 8/20 and session VWAP agree" }, { param: "Exit", value: "Same contract’s 30-minute bid" }],
  },
  {
    id: "v2_spy_afternoon_reversal", name: "SPY Afternoon Reversal V2", emoji: "↗",
    setup: "After a meaningful morning selloff, SPY forms a higher low and then breaks above a completed swing high during the early afternoon.",
    entry: "The completed five-minute structure must be above VWAP. The paper model records the following one-minute option ask, not a hindsight price.",
    stop: "The confirmed higher low or one ATR below the entry—whichever is lower—is the structural invalidation.",
    target: "The reviewed study exits the same selected contract 30 minutes after entry at its observed bid.",
    notes: "SPY calls only, from 1:00–2:00 PM ET. This is not the retired all-day generic Afternoon Reversal strategy.",
    evidence: "The selected long-only context passed both earlier and later paid option-quote periods: 12 measured signals, with positive average markouts in each period.",
    tags: ["paper", "afternoon", "reversal"],
    tuning: [{ param: "Window", value: "1:00–2:00 PM ET" }, { param: "Structure", value: "Morning selloff → higher low → break above swing high" }, { param: "Confirmation", value: "Completed 5-minute close above VWAP" }, { param: "Exit", value: "Same contract’s 30-minute bid" }],
  },
  {
    id: "v2_momentum", name: "TSLA Adaptive Momentum V2", emoji: "⚡",
    setup: "At each half-hour check, compare TSLA's move with its normal move at that same time across the prior 14 sessions.",
    entry: "A completed one-minute bar outside the adaptive zone signals direction; entry uses the next minute's actual option ask.",
    stop: "The tested version uses account-wide protections and closes the same selected contract at 3:59 PM ET.",
    target: "This version has a fixed 3:59 PM bid exit so the entry rule can be measured consistently.",
    notes: "TSLA only. It ignores movement inside its adaptive normal-movement zone instead of treating every candle as a signal.",
    evidence: "What we know: 85 earlier trades and 20 later trades passed the predeclared average, median, and profit-factor checks using paid option ask/bid prices.",
    tags: ["paper", "momentum", "1-minute"],
    tuning: [{ param: "Baseline", value: "Exactly 14 prior TSLA sessions" }, { param: "Timing", value: "10:00–15:30 ET at half-hour checks" }, { param: "Exit", value: "Same contract's 3:59 PM bid" }],
  },
  {
    id: "v2_two_leg", name: "TSLA Two-Leg Trend Pullback V2", emoji: "↗",
    setup: "After 9:45 ET, TSLA must make a real move away from the 9:45 reference: price stays on the correct side of VWAP, EMA 9 is above or below EMA 20, and the first leg travels at least one ATR.",
    entry: "It does not chase that first move. Price must pull back 0.25–1.25 ATR to EMA 9 without closing through VWAP, then a finished one-minute candle must reclaim the pullback’s prior high or low. The following minute’s selected option ask is the entry reference.",
    stop: "The pullback extreme is the underlying invalidation. If price closes through VWAP or the trend EMAs cross, the setup is cancelled instead of being forced.",
    target: "The reviewed model holds the same selected contract for 90 minutes, then uses its executable bid—not a midpoint or a made-up option price.",
    notes: "TSLA only. This is a morning continuation pattern, not a generic all-day trend signal and not the old retired Trend Continuation rule.",
    evidence: "Older data selected the baseline version: 108 option markouts, +3.19% average, +2.04% median, 1.48 profit factor. The untouched later period also passed: 19 markouts, +4.00% average, +0.50% median, 1.51 profit factor.",
    tags: ["paper", "TSLA", "1-minute", "VWAP"],
    tuning: [{ param: "Reference", value: "09:45 ET close" }, { param: "First leg", value: "≥ 1 ATR with VWAP + EMA 9/20 agreement" }, { param: "Pullback", value: "0.25–1.25 ATR into EMA 9; VWAP must hold" }, { param: "Entry", value: "Completed 1-minute reclaim, then next-minute option ask" }, { param: "Exit", value: "Same contract’s 90-minute bid" }],
  },
];

export function Playbooks() {
  const [tab,           setTab]           = useState<"playbooks" | "log-guide" | "how-it-works">("playbooks");
  const [search,        setSearch]        = useState("");
  const [activeCategory, setActiveCategory] = useState<string | null>(null);
  const [openSection,   setOpenSection]   = useState<string | null>("routine");   // first section open by default
  const { data: settings } = useQuery({ queryKey: ["settings"], queryFn: api.settings.get });
  const currentStrategies = useMemo(() => CURRENT_STRATEGIES.filter((strategy) => (
    strategy.id === "v2_orb" ? Boolean(settings?.strategy_orb_pullback_v2_enabled) :
    strategy.id === "v2_trend" ? Boolean(settings?.strategy_spy_trend_cont_v2_enabled) :
    strategy.id === "v2_spy_fvg" ? Boolean(settings?.strategy_spy_afternoon_fvg_v2_enabled) :
    (strategy.id === "v2_spy_afternoon_reversal" || strategy.id === "v2_momentum") ? false :
    Boolean(settings?.strategy_tsla_two_leg_trend_pullback_v2_enabled)
  )), [settings]);

  // Filter + group log codes by search query and active category
  const filteredLogs = useMemo(() => {
    const q = search.toLowerCase().trim();
    return LOG_CODES.filter((item) => {
      const matchSearch = !q || (
        item.code.toLowerCase().includes(q) ||
        item.plain.toLowerCase().includes(q) ||
        item.detail.toLowerCase().includes(q) ||
        item.tag.toLowerCase().includes(q)
      );
      const matchCat = !activeCategory || item.tag === activeCategory;
      return matchSearch && matchCat;
    });
  }, [search, activeCategory]);

  // Group filtered results by tag
  const grouped = useMemo(() => {
    const map: Record<string, typeof LOG_CODES> = {};
    for (const item of filteredLogs) {
      if (!map[item.tag]) map[item.tag] = [];
      map[item.tag].push(item);
    }
    return map;
  }, [filteredLogs]);

  return (
    <div className="p-4 flex flex-col gap-4" data-legacy-strategy-count={STRATEGIES.length}>
      {/* Tab bar */}
      <div className="flex gap-2 border-b pb-2" style={{ borderColor: "var(--border)" }}>
        {(["playbooks", "log-guide", "how-it-works"] as const).map((t) => (
          <button
            key={t}
            className={`btn btn-sm ${tab === t ? "btn-primary" : "btn-ghost"}`}
            onClick={() => setTab(t)}
          >
            {t === "playbooks" ? "Strategy Playbook" : t === "log-guide" ? "Log Dictionary" : "How It Works"}
          </button>
        ))}
      </div>

      {tab === "log-guide" && (
        <div className="flex flex-col gap-4">

          {/* Search + category filters */}
          <div className="flex flex-col gap-2">
            <div className="relative">
              <Search
                size={14}
                className="absolute left-3 top-1/2 -translate-y-1/2"
                style={{ color: "var(--ink-muted)" }}
              />
              <input
                type="text"
                placeholder="Search event codes, descriptions…"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="input w-full pl-8 text-sm"
                style={{ maxWidth: 480 }}
              />
            </div>
            {/* Category pills */}
            <div className="flex flex-wrap gap-1.5">
              <button
                className={`btn btn-sm ${activeCategory === null ? "btn-primary" : "btn-ghost"}`}
                onClick={() => setActiveCategory(null)}
              >
                All
              </button>
              {LOG_CATEGORIES.map((cat) => (
                <button
                  key={cat.key}
                  className={`btn btn-sm ${activeCategory === cat.key ? "btn-primary" : "btn-ghost"}`}
                  onClick={() => setActiveCategory(activeCategory === cat.key ? null : cat.key)}
                >
                  {cat.emoji} {cat.label}
                </button>
              ))}
            </div>
          </div>

          {/* Results count */}
          <p className="text-xs" style={{ color: "var(--ink-muted)" }}>
            {filteredLogs.length} {filteredLogs.length === 1 ? "entry" : "entries"}
            {search ? ` matching "${search}"` : ""}
            {activeCategory ? ` in "${LOG_CATEGORIES.find(c => c.key === activeCategory)?.label}"` : ""}
          </p>

          {/* Grouped results */}
          {filteredLogs.length === 0 ? (
            <div className="card px-4 py-8 text-center" style={{ color: "var(--ink-muted)" }}>
              No log codes match your search.
            </div>
          ) : (
            LOG_CATEGORIES
              .filter(cat => grouped[cat.key]?.length)
              .map((cat) => (
                <div key={cat.key} className="flex flex-col gap-2">
                  {/* Category header */}
                  <div className="flex items-center gap-2 pt-1">
                    <span className="text-base">{cat.emoji}</span>
                    <span className="text-xs font-semibold uppercase tracking-widest"
                          style={{ color: "var(--ink-muted)" }}>
                      {cat.label}
                    </span>
                    <span className="text-xs px-1.5 py-0.5 rounded-full"
                          style={{ background: "var(--muted)", color: "var(--ink-muted)" }}>
                      {grouped[cat.key].length}
                    </span>
                    <div className="flex-1 border-t" style={{ borderColor: "var(--border)" }} />
                  </div>

                  {/* Entries in this category */}
                  {grouped[cat.key].map((item) => (
                    <div key={item.code}
                         className="card px-4 py-3 flex gap-4 items-start"
                         style={{ borderLeft: `3px solid var(--accent)` }}>
                      <div className="flex flex-col gap-1 min-w-0">
                        {/* Code + badge on same row */}
                        <div className="flex items-center gap-2 flex-wrap">
                          <code
                            className="text-xs font-mono font-semibold px-1.5 py-0.5 rounded"
                            style={{ background: "var(--muted)", color: "var(--accent)" }}
                          >
                            {item.code}
                          </code>
                          <span className={`badge ${TAG_BADGE[item.tag] ?? "badge-blue"}`}>
                            {item.tag}
                          </span>
                        </div>
                        {/* Plain-English title */}
                        <span className="text-sm font-medium" style={{ color: "var(--ink)" }}>
                          {item.plain}
                        </span>
                        {/* Detail */}
                        <span className="text-xs leading-relaxed" style={{ color: "var(--ink-muted)" }}>
                          {item.detail}
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              ))
          )}
        </div>
      )}

      {tab === "playbooks" && (
      <div className="flex flex-col gap-4">
      {currentStrategies.length === 0 ? (
        <div className="card p-5 text-sm" style={{ color: "var(--ink-muted)" }}>
          No paper strategies are switched on. Turn one on in Settings → Paper strategy controls to see its lesson here.
        </div>
      ) : (
        <StrategyPlaybookExperience activeLessonIds={currentStrategies.map((strategy) => strategy.id as "v2_orb" | "v2_trend" | "v2_spy_fvg" | "v2_spy_afternoon_reversal" | "v2_momentum")} />
      )}

      <details className="card p-4">
        <summary className="text-sm font-semibold cursor-pointer" style={{ color: "var(--ink)" }}>
          Technical reference (optional)
        </summary>
        <div className="flex flex-col gap-4 mt-4">
      {currentStrategies.length === 0 ? (
        <div className="card p-5 text-sm" style={{ color: "var(--ink-muted)" }}>
          No paper strategies are switched on. Turn one on in Settings → Paper strategy controls to see its lesson here.
        </div>
      ) : (

      <div className="grid gap-4" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(360px, 1fr))" }}>
        {currentStrategies.map((s) => (
          <div key={s.id} className="card p-4 flex flex-col gap-3">
            {/* Header */}
            <div className="flex items-start justify-between gap-2">
              <div>
                <span className="text-2xl">{s.emoji}</span>
                <h3 className="text-sm font-semibold mt-1" style={{ color: "var(--ink)" }}>
                  {s.name}
                </h3>
              </div>
              <div className="flex flex-wrap gap-1 justify-end">
                {s.tags.map((t) => (
                  <span key={t} className={`badge ${TAG_COLORS[t] ?? "badge-blue"}`}>{t}</span>
                ))}
              </div>
            </div>

            {/* Rules table */}
            <div className="flex flex-col gap-2 text-xs">
              {[
                { label: "Setup",  value: s.setup },
                { label: "Entry",  value: s.entry },
                { label: "Stop",   value: s.stop  },
                { label: "Target", value: s.target },
              ].map((row) => (
                <div key={row.label} className="flex gap-2">
                  <span
                    className="shrink-0 font-semibold uppercase tracking-wide w-14"
                    style={{ color: "var(--ink-muted)" }}
                  >
                    {row.label}
                  </span>
                  <span style={{ color: "var(--ink)" }}>{row.value}</span>
                </div>
              ))}
            </div>

            {/* Tuning numbers */}
            <div className="flex flex-col gap-1">
              <span
                className="text-xs font-semibold uppercase tracking-widest"
                style={{ color: "var(--ink-muted)" }}
              >
                ⚙️ Live Tuning
              </span>
              <div
                className="rounded-lg px-3 py-2 flex flex-col gap-1"
                style={{ background: "var(--muted)" }}
              >
                {s.tuning.map((t) => {
                  const tip =
                    t.param.startsWith("RVOL") ? GLOSSARY.RVOL :
                    t.param.startsWith("ATR")  ? GLOSSARY.ATR  :
                    t.param === "VWAP"         ? GLOSSARY.VWAP :
                    "";
                  return (
                    <div key={t.param} className="flex gap-2 text-xs">
                      <span
                        className="shrink-0 font-mono"
                        style={{ color: "var(--ink-muted)", width: 130 }}
                      >
                        {tip ? <Tooltip text={tip}>{t.param}</Tooltip> : t.param}
                      </span>
                      <span className="font-mono font-semibold" style={{ color: "var(--accent)" }}>
                        {t.value}
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>

            {/* Notes */}
            <div
              className="text-xs px-3 py-2 rounded-lg"
              style={{ background: "var(--muted)", color: "var(--ink-muted)" }}
            >
              💡 {s.notes}
            </div>
            <div
              className="text-xs px-3 py-2 rounded-lg leading-relaxed"
              style={{ background: "color-mix(in srgb, var(--accent) 8%, var(--surface))", color: "var(--ink-muted)", borderLeft: "3px solid var(--accent)" }}
            >
              <strong style={{ color: "var(--ink)" }}>Research status:</strong> {s.evidence ?? "No reviewed evidence status is available."}
            </div>
          </div>
        ))}
      </div>
      )}

      {/* Global risk parameters */}
      <div className="flex flex-col gap-2 mt-2">
        <div className="flex items-center gap-2">
          <span className="text-base">🛡️</span>
          <span className="text-sm font-semibold" style={{ color: "var(--ink)" }}>
            Global Risk &amp; Exit Parameters
          </span>
          <span className="text-xs" style={{ color: "var(--ink-muted)" }}>
            — shared across all strategies
          </span>
        </div>
        <div
          className="card p-4 grid gap-x-8 gap-y-1.5"
          style={{ gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))" }}
        >
          {GLOBAL_PARAMS.map((g) => {
            const gTip =
              g.param.startsWith("RVOL")      ? GLOSSARY.RVOL       :
              g.param.startsWith("ATR")       ? GLOSSARY.ATR        :
              g.param.includes("Stage 1")     ? GLOSSARY["Stage 1"] :
              g.param.includes("Stage 2") || g.param.includes("trail") ? GLOSSARY["ATR Trail"] :
              g.param.startsWith("VWAP")      ? GLOSSARY.VWAP       :
              "";
            return (
            <div key={g.param} className="flex gap-2 text-xs items-baseline">
              <span
                className="shrink-0 font-mono"
                style={{ color: "var(--ink-muted)", width: 148 }}
              >
                {gTip ? <Tooltip text={gTip}>{g.param}</Tooltip> : g.param}
              </span>
              <span className="font-mono font-semibold" style={{ color: "var(--accent)" }}>
                {g.value}
              </span>
              {g.note && (
                <span className="text-xs" style={{ color: "var(--ink-muted)" }}>
                  — {g.note}
                </span>
              )}
            </div>
            );
          })}
        </div>
      </div>

        </div>
      </details>
      </div>
      )}

      {tab === "how-it-works" && (
        <div className="flex flex-col gap-3 max-w-3xl">
          <div>
            <h2 className="text-base font-semibold" style={{ color: "var(--ink)" }}>How the Bot Works</h2>
            <p className="text-sm mt-0.5" style={{ color: "var(--ink-muted)" }}>
              A complete walkthrough — from market open to position close. Click any section to expand it.
            </p>
          </div>
          {HOW_IT_WORKS.map((sec) => {
            const isOpen = openSection === sec.id;
            return (
              <div key={sec.id} className="card overflow-hidden">
                {/* Accordion header */}
                <button
                  className="w-full flex items-center justify-between px-4 py-3 text-left"
                  onClick={() => setOpenSection(isOpen ? null : sec.id)}
                  style={{ background: "none", border: "none", cursor: "pointer" }}
                >
                  <div className="flex items-center gap-3">
                    <span className="text-xl">{sec.emoji}</span>
                    <span className="text-sm font-semibold" style={{ color: "var(--ink)" }}>{sec.title}</span>
                  </div>
                  {isOpen
                    ? <ChevronDown size={16} style={{ color: "var(--ink-muted)", flexShrink: 0 }} />
                    : <ChevronRight size={16} style={{ color: "var(--ink-muted)", flexShrink: 0 }} />}
                </button>

                {/* Accordion body */}
                {isOpen && (
                  <div
                    className="flex flex-col gap-2.5 px-4 pb-4"
                    style={{ borderTop: "1px solid var(--border)" }}
                  >
                    {sec.body.map((line, i) => {
                      // Lines that start with a number (gate list) get slightly different styling
                      const isNumbered = /^\d+\./.test(line);
                      return (
                        <p
                          key={i}
                          className={`text-xs leading-relaxed ${isNumbered ? "pl-2" : ""}`}
                          style={{ color: "var(--ink-muted)", paddingTop: i === 0 ? 12 : 0 }}
                        >
                          {isNumbered ? (
                            <>
                              <span className="font-semibold" style={{ color: "var(--accent)" }}>
                                {line.match(/^\d+\./)?.[0]}{" "}
                              </span>
                              <span>{line.replace(/^\d+\.\s*/, "")}</span>
                            </>
                          ) : line}
                        </p>
                      );
                    })}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
