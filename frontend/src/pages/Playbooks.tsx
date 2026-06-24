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
};

// ── Log event code explanations ───────────────────────────────────────────
const LOG_CODES: { code: string; plain: string; detail: string; tag: string }[] = [
  { code: "logging_initialised",  tag: "system",  plain: "Bot started up",                      detail: "The bot just launched and its logging system is ready." },
  { code: "Trade_Signal",         tag: "signal",  plain: "A valid trade setup was found",        detail: "All gates passed: RVOL, R:R, spread, and strategy rules. The bot is about to place an order." },
  { code: "entry_placed",         tag: "order",   plain: "Order submitted to broker",            detail: "The buy/sell order was sent to Alpaca. Waiting for fill confirmation." },
  { code: "entry_filled",         tag: "order",   plain: "Order filled — position is open",      detail: "Broker confirmed the order executed. The trade is now live." },
  { code: "stage1_exit",          tag: "exit",    plain: "Took first half profit (Stage 1)",     detail: "Price hit the 1:1 R:R target. Half the position was closed to lock in gains." },
  { code: "stage2_exit",          tag: "exit",    plain: "Closed remaining position (Stage 2)",  detail: "The trailing stop or time-box triggered on the remaining contracts." },
  { code: "stop_hit",             tag: "exit",    plain: "Stop loss was triggered",              detail: "Price moved against the trade and hit the pre-set stop. Position closed to protect capital." },
  { code: "time_box_exit",        tag: "exit",    plain: "Trade closed — time limit reached",    detail: "The trade exceeded its maximum hold time (45 min, or 90 min if Stage 1 was hit)." },
  { code: "bar_evaluation",       tag: "think",   plain: "Bot checked the latest candle",        detail: "Every 1-minute close the bot runs all strategy checks and logs its decision." },
  { code: "RVOL_gate_pass",       tag: "gate",    plain: "Volume check passed",                  detail: "Relative volume (today vs. average) was high enough to consider a trade." },
  { code: "RVOL_gate_fail",       tag: "gate",    plain: "Volume too low — skipping",            detail: "Not enough trading volume. Low volume = unreliable breakouts. Bot waits." },
  { code: "rr_gate_pass",         tag: "gate",    plain: "Risk:Reward ratio is good",            detail: "The potential profit is at least the minimum multiple of the potential loss." },
  { code: "rr_gate_fail",         tag: "gate",    plain: "Risk:Reward too poor — skipping",      detail: "The reward wasn't worth the risk at current prices. Bot passes on the trade." },
  { code: "spread_gate_fail",     tag: "gate",    plain: "Bid-ask spread too wide",              detail: "The gap between buy and sell price was >10%, eating too much of the trade's edge." },
  { code: "orb_already_triggered",tag: "gate",    plain: "ORB already fired on this ticker today",detail: "The bot only takes one ORB trade per ticker per day to avoid overtrading." },
  { code: "kill_lock_active",     tag: "risk",    plain: "Daily loss limit hit — bot locked",    detail: "Total losses for the day exceeded the max. Bot stops trading until tomorrow." },
  { code: "flip_trade",           tag: "signal",  plain: "Bot flipped direction on a reversal",  detail: "A failed trade reversed hard. The bot flipped from long→short (or vice versa)." },
  { code: "network_error",        tag: "system",  plain: "API connection problem",               detail: "The broker API returned an error or timed out. Bot will retry automatically." },
  { code: "ghost_position_detected",tag:"risk",   plain: "Open position found without a DB record",detail: "Alpaca shows an open position the bot doesn't have in its trade journal. Needs review." },
  { code: "balance_update",       tag: "system",  plain: "Account balance refreshed",            detail: "The bot fetched the latest account balance from Alpaca." },
];

const TAG_BADGE: Record<string, string> = {
  system: "badge-blue",
  signal: "badge-green",
  order:  "badge-blue",
  exit:   "badge-red",
  think:  "badge-yellow",
  gate:   "badge-yellow",
  risk:   "badge-red",
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
      <div>
        <h2 className="text-base font-semibold" style={{ color: "var(--ink)" }}>Strategy Playbooks</h2>
        <p className="text-sm mt-0.5" style={{ color: "var(--ink-muted)" }}>
          Reference cards for every strategy the bot trades. All use the same 1% risk model and two-stage exit.
        </p>
      </div>

      <div className="grid gap-4 mt-3" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(340px, 1fr))" }}>
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
      )}
    </div>
  );
}
