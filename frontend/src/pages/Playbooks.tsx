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
    target: "Swing high/low that created the FVG move. Stage 1 at +50%, Stage 2 trail.",
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
  { param: "Stage 1 target",     value: "+50% on option premium",  note: "Exits 50% of contracts" },
  { param: "Stage 2 trail lock", value: "+15% profit floor",        note: "Floor after Stage 1 fires" },
  { param: "ATR trail mult.",    value: "2.0× ATR (underlying)",    note: "peak − 2× ATR14" },
  { param: "ATR trail warmup",   value: "5 min minimum in trade",   note: "Trail doesn't arm before this" },
  { param: "Hard stop (loss)",   value: "−50% on option premium" },
  { param: "Momentum stop",      value: "−20% (early exit)",        note: "Cuts before full stop if trend collapses" },
  { param: "Time-box (losing)",  value: "20 min max" },
  { param: "Time-box (winner)",  value: "90 min after Stage 1" },
  { param: "Spread max",         value: "$0.10 bid-ask" },
  { param: "Min R:R (bootstrap)","value": "1.2× (balance < $5k)" },
  { param: "Min R:R (standard)", value: "1.6×" },
  { param: "Max positions",      value: "2 concurrent" },
  { param: "Kill lock",          value: "24 hrs after daily cap" },
  { param: "RVOL baseline",      value: "5-min bars, 10-day same-slot avg" },
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
import { Search } from "lucide-react";

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

export function Playbooks() {
  const [tab,    setTab]    = useState<"playbooks" | "log-guide">("playbooks");
  const [search, setSearch] = useState("");
  const [activeCategory, setActiveCategory] = useState<string | null>(null);

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
    <div className="p-4 flex flex-col gap-4">
      {/* Tab bar */}
      <div className="flex gap-2 border-b pb-2" style={{ borderColor: "var(--border)" }}>
        {(["playbooks", "log-guide"] as const).map((t) => (
          <button
            key={t}
            className={`btn btn-sm ${tab === t ? "btn-primary" : "btn-ghost"}`}
            onClick={() => setTab(t)}
          >
            {t === "playbooks" ? "Strategy Playbooks" : "Log Dictionary"}
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
        <div>
          <h2 className="text-base font-semibold" style={{ color: "var(--ink)" }}>Strategy Playbooks</h2>
          <p className="text-sm mt-0.5" style={{ color: "var(--ink-muted)" }}>
            Reference cards for every strategy the bot trades. All use the same risk model and two-stage exit.
          </p>
        </div>

      <div className="grid gap-4" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(360px, 1fr))" }}>
        {STRATEGIES.map((s) => (
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
                {s.tuning.map((t) => (
                  <div key={t.param} className="flex gap-2 text-xs">
                    <span
                      className="shrink-0 font-mono"
                      style={{ color: "var(--ink-muted)", width: 130 }}
                    >
                      {t.param}
                    </span>
                    <span className="font-mono font-semibold" style={{ color: "var(--accent)" }}>
                      {t.value}
                    </span>
                  </div>
                ))}
              </div>
            </div>

            {/* Notes */}
            <div
              className="text-xs px-3 py-2 rounded-lg"
              style={{ background: "var(--muted)", color: "var(--ink-muted)" }}
            >
              💡 {s.notes}
            </div>
          </div>
        ))}
      </div>

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
          {GLOBAL_PARAMS.map((g) => (
            <div key={g.param} className="flex gap-2 text-xs items-baseline">
              <span
                className="shrink-0 font-mono"
                style={{ color: "var(--ink-muted)", width: 148 }}
              >
                {g.param}
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
          ))}
        </div>
      </div>

      </div>
      )}
    </div>
  );
}
