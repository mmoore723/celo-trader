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
}

const STRATEGIES: Strategy[] = [
  {
    id: "orb",
    name: "Opening Range Breakout",
    emoji: "🎯",
    setup:  "Price forms a tight range during 9:30–9:44 ET. Wait for the first 15-minute candle to close.",
    entry:  "Enter on a candle close above ORB high (long) or below ORB low (short). RVOL ≥ 1.5×.",
    stop:   "Below ORB low (long) or above ORB high (short). Never more than 20% from entry.",
    target: "Stage 1: 1:1 R:R. Stage 2: let runners trail. Time-box at 45 min (90 min if Stage 1 hit).",
    notes:  "Highest-probability signal. Avoid if SPY is below VWAP — broad market sell bias.",
    tags:   ["primary", "momentum"],
  },
  {
    id: "vwap",
    name: "VWAP Pullback",
    emoji: "📈",
    setup:  "Trending stock pulls back to VWAP after a strong first push above/below.",
    entry:  "Bounce off VWAP with volume confirmation and MSA trend alignment. RVOL ≥ 1.3×.",
    stop:   "Below VWAP (long) or above VWAP (short). Tight — VWAP is the thesis level.",
    target: "Previous session high/low or 2× ATR.",
    notes:  "Works best when VWAP is flat or slightly sloped, not during chop.",
    tags:   ["secondary", "mean-reversion"],
  },
  {
    id: "fvg",
    name: "Fair Value Gap",
    emoji: "⚡",
    setup:  "3-bar pattern: bullish (or bearish) impulse candle leaves a gap between candle 1's high and candle 3's low.",
    entry:  "Price retests the FVG zone (fills the gap). Enter on first candle that closes into the zone.",
    stop:   "Beyond the 50% level of the FVG.",
    target: "Swing high/low that created the FVG move.",
    notes:  "Requires BOS/MSS confirmation to avoid fading into a trend.",
    tags:   ["structural", "ICT"],
  },
  {
    id: "bos",
    name: "BOS / MSS",
    emoji: "🔓",
    setup:  "Break of Structure: price takes out a prior swing high (bullish) or swing low (bearish).",
    entry:  "Enter on BOS candle close or first retest of broken level.",
    stop:   "Structural stop below the last higher low (bullish) or above last lower high (bearish).",
    target: "Next significant swing level.",
    notes:  "MSS (Market Structure Shift) is the strongest signal — trend reversal, not continuation.",
    tags:   ["structural", "smc"],
  },
  {
    id: "flip",
    name: "Flip Trading",
    emoji: "🔄",
    setup:  "Bot has an open directional trade that fails its initial target and reverses hard.",
    entry:  "Bot auto-flips direction when price crosses the ORB breakout level in the opposite direction.",
    stop:   "Mirror of original — now the opposite ORB level.",
    target: "Same 1:1 Stage 1, then trail.",
    notes:  "Enabled/disabled in Settings. Adds churn risk — keep off if RVOL is low.",
    tags:   ["adaptive", "risk"],
  },
  {
    id: "chan",
    name: "Channel Breakout",
    emoji: "🏹",
    setup:  "Price is range-bound for ≥ 4 bars. Identify horizontal resistance/support.",
    entry:  "Breakout candle closes above resistance (long) or below support (short) with RVOL ≥ 1.5×.",
    stop:   "Back inside the channel.",
    target: "Channel height projected from breakout point.",
    notes:  "Avoid in the first 15 minutes (ORB window) and last 20 minutes of session.",
    tags:   ["breakout", "range"],
  },
  {
    id: "mid",
    name: "Mid-Day Breakdown",
    emoji: "📉",
    setup:  "After the opening range plays out (10:30–13:00 ET), price collapses below OR Low with VWAP acting as resistance. Market structure has already printed a Lower High — the bullish thesis is broken.",
    entry:  "Enter PUT when: price closes below OR Low AND below VWAP AND MSA confirms a Lower High AND volume > 1.5× its 20-bar average.",
    stop:   "Above OR Low (the broken level). If price reclaims OR Low, setup is invalid.",
    target: "Stage 1: 1:1 R:R below entry. Stage 2: trail to next swing low. Time-box 45 min.",
    notes:  "Bearish-only strategy. Only triggers 10:30–13:00 ET — avoids the chaotic open and the dead midday grind. Requires both structure (Lower High) and volume to fire.",
    tags:   ["secondary", "bearish"],
  },
  {
    id: "trend",
    name: "Trend Continuation",
    emoji: "🌊",
    setup:  "After a trend is already established, price pulls back to a key level (Higher Low for uptrends, Lower High for downtrends) and resumes. This is the 2nd or 3rd entry, not the first — the trend must already be proven.",
    entry:  "Bullish: close above the Higher Low bar's close with RVOL ≥ 1.2× and price above VWAP. Bearish: close below the Lower High bar's close with RVOL ≥ 1.2× and price below VWAP. Pivot must be within last 20 bars (fresh, not stale).",
    stop:   "Below the Higher Low (bullish) or above the Lower High (bearish). Structure is the anchor.",
    target: "Previous swing high (bullish) or previous swing low (bearish). Stage 2 lets runners trail.",
    notes:  "Lowest RVOL threshold (1.2×) because the trend does the heavy lifting. Active 9:45 AM–2:30 PM ET. Never take a TREND_CONT trade if the pivot is more than 20 bars old — momentum has faded.",
    tags:   ["secondary", "momentum"],
  },
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

import { useState } from "react";

export function Playbooks() {
  const [tab, setTab] = useState<"playbooks" | "log-guide">("playbooks");

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
            {t === "playbooks" ? "Strategy Playbooks" : "How to Read the Log"}
          </button>
        ))}
      </div>

      {tab === "log-guide" && (
        <div className="flex flex-col gap-3">
          <p className="text-sm" style={{ color: "var(--ink-muted)" }}>
            Every line in "Bot Thinking" has an event code. Here's what each one means in plain English.
          </p>
          {LOG_CODES.map((item) => (
            <div key={item.code} className="card px-4 py-3 flex gap-4 items-start">
              <span className={`badge shrink-0 mt-0.5 ${TAG_BADGE[item.tag] ?? "badge-blue"}`}>
                {item.tag}
              </span>
              <div className="flex flex-col gap-0.5 min-w-0">
                <span className="font-mono text-xs font-semibold" style={{ color: "var(--accent)" }}>
                  {item.code}
                </span>
                <span className="text-sm font-medium" style={{ color: "var(--ink)" }}>
                  {item.plain}
                </span>
                <span className="text-xs" style={{ color: "var(--ink-muted)" }}>
                  {item.detail}
                </span>
              </div>
            </div>
          ))}
        </div>
      )}

      {tab === "playbooks" && (
      <div className="flex flex-col gap-4">
        <div>
          <h2 className="text-base font-semibold" style={{ color: "var(--ink)" }}>Strategy Playbooks</h2>
          <p className="text-sm mt-0.5" style={{ color: "var(--ink-muted)" }}>
            Reference cards for every strategy the bot trades. All use the same 1% risk model and two-stage exit.
          </p>
        </div>

      <div className="grid gap-4" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(340px, 1fr))" }}>
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
      </div>
      )}
    </div>
  );
}
