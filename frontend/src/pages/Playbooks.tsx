import { Foundations } from "../components/learning/Foundations";
/**
 * Learning Hub plus the strategy and operations reference material.
 */

import { useState, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { Search, ChevronDown, ChevronRight } from "lucide-react";
import { PairLearning } from "../components/learning/PairLearning";
import { EnabledLearningPairs } from "../components/learning/EnabledLearningPairs";
import { useSearchParams } from "react-router-dom";
import { GLOSSARY } from "../lib/glossary";
import { api } from "../lib/api";
import { useAuth } from "../contexts/AuthContext";

const LOG_CODES = [
  { code: "bar_eval", tag: "think", plain: "Per-candle evaluation", detail: "Shows what a promoted strategy saw and why it did or did not advance." },
  { code: "Trade_Signal", tag: "signal", plain: "Promoted setup qualified", detail: "The setup passed its reviewed definition and advanced to account safeguards." },
  { code: "entry_placed", tag: "order", plain: "Order submitted", detail: "The selected option order was sent to the configured broker account." },
  { code: "entry_filled", tag: "order", plain: "Order filled", detail: "The broker confirmed the position and its reviewed exit clock began." },
  { code: "entry_rejected", tag: "order", plain: "Order rejected", detail: "The broker refused the order; no position was opened." },
  { code: "spread_gate_fail", tag: "gate", plain: "Spread too wide", detail: "The option bid/ask spread failed the account liquidity safeguard." },
  { code: "affordability_block", tag: "risk", plain: "Contract unaffordable", detail: "No reviewed contract fit the account's current spending limit." },
  { code: "stop_hit", tag: "exit", plain: "Risk exit", detail: "The position reached its defined safety exit." },
  { code: "time_box_exit", tag: "exit", plain: "Reviewed timed exit", detail: "The same selected contract reached the strategy's tested exit time." },
];

const TAG_BADGE: Record<string, string> = { system: "badge-blue", signal: "badge-green", order: "badge-blue", exit: "badge-red", think: "badge-yellow", gate: "badge-yellow", risk: "badge-red" };


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
      "9:45 AM ET — The promoted Opening-Range Pullback and Two-Leg Trend Pullback can begin evaluating completed data.",
      "1:30 PM ET — The promoted Afternoon Fair Value Gap enters its reviewed observation window.",
      "3:55 PM ET — Hard session cutoff. All remaining positions are closed regardless of P&L. Options expire and after-hours liquidity evaporates — this is non-negotiable.",
      "After 4:00 PM ET — Bot enters deep sleep. No API calls, no evaluation. Wakes at 8:00 AM next trading day.",
    ],
  },
  {
    id: "scanner",
    emoji: "🔍",
    title: "How the Watchlist Gets Built",
    body: [
      "The scanner screens Alpaca’s active optionable stock list before the open, then refreshes it after 9:30 ET using the official opening print and current activity.",
      "Filter 1 — Price: stock must trade above $10. Sub-$10 names have thin options chains and erratic gaps.",
      "Filter 2 — Gap: the open price must be 1–4% away from yesterday's close (either direction). Below 1% = no real move. Above 4% = already overextended before the bell. ETFs get a lower floor of 0.5% because even a 0.5% gap on SPY is a real institutional move.",
      "Filter 3 — Volume: average daily volume over 20 days must exceed 2 million shares. Low-volume names have wide options spreads and fake breakouts.",
      "Filter 4 — ATR: the 14-day Average True Range must exceed $1. This ensures the stock actually moves enough for the option premium to be meaningful.",
      "Filter 5 — RVOL: relative volume (today's shares so far vs. historical same-time average) must be ≥ 2× for stocks, ≥ 1.5× for ETFs. Elevated volume means institutions are involved — the move is more likely real.",
      "Scoring: survivors are ranked by RVOL × gap size × ATR factor × liquidity bonus. ETFs get a 1.15× liquidity bonus because their options chains are deeper and spreads tighter.",
      "Affordability check: the scanner also estimates whether options on a ticker would actually fit your risk budget. If the estimated stop-loss on 1 contract (option premium × 30%) exceeds your risk budget, the ticker is heavily de-ranked — it would just be skipped every tick anyway.",
      "The top 30 strategy-fit candidates join SPY, QQQ, and every ticker pinned in Settings. The shortlist balances compressed-range, inside-day, trend/pullback, and volatility candidates. This same list powers the Daily Brief and research collector, so every displayed candidate receives one-minute candle coverage.",
    ],
  },
  {
    id: "tick",
    emoji: "⏱️",
    title: "How the Bot Evaluates Tickers",
    body: [
      "Every minute the bot evaluates the complete collection universe in one pass: Settings pins, SPY/QQQ anchors, and every dynamic ticker displayed in the Daily Brief. This is the 'batch tick' approach. Old design evaluated one ticker every 10 seconds, so some bars were missed entirely.",
      "For each ticker in the pass, the bot: (1) fetches today's 1-minute bars from Alpaca, (2) augments with 15 days of 5-minute historical bars for accurate RVOL calculation, (3) runs all enabled strategies, (4) checks all entry gates, (5) selects a contract and places an order if everything passes.",
      "After processing all tickers, the bot sleeps to the next 60-second bar boundary. This ensures every evaluation sees a fresh closed bar rather than re-checking the same partial bar twice.",
      "The Bot Thinking log on the Live Trading page shows one entry per bar per ticker — you can see exactly what the bot considered and why it decided not to trade.",
      "Scanner Opportunities is the durable audit trail. It separates setup detection, qualification, contract planning, order submission, and broker outcome so an observed setup is never presented as an order.",
    ],
  },
  {
    id: "signals",
    emoji: "📡",
    title: "How Strategies Generate Signals",
    body: [
      "The router contains only promoted evaluators: Opening-Range Pullback, Trend Continuation, and Afternoon Fair Value Gap. Two-Leg Trend Pullback enters through its reviewed one-minute state machine.",
      "Each strategy keeps the same timeframe, setup, contract-selection rule, and timed exit that passed its paid option-quote study. Account safeguards can still block an otherwise valid setup.",
    ],
  },
  {
    id: "contracts",
    emoji: "📄",
    title: "Choosing the Option Contract",
    body: [
      "Only after a reviewed chart setup completes does the bot request the Tradier option chain for that ticker and direction.",
      "The reviewed V2 selector uses 7–21 DTE, the nearest out-of-the-money strike, an ask from $0.80 to $10.00, and a bid/ask spread no wider than 8% of mid.",
      "The selected contract must also fit the active account's position budget. If one contract does not fit, the setup is recorded with the exact affordability reason and no order is sent.",
      "Entry evidence uses the executable ask after the chart signal. Exit evidence uses the same contract's executable bid at that strategy's registered 30- or 90-minute horizon.",
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
      "A V2 setup must first match the exact reviewed strategy, ticker, timeframe, and signal source in the server catalog. A browser toggle cannot invent a strategy or widen its ticker scope.",
      "Before a new entry, the runtime verifies that the evidence artifact still matches the deployed implementation. A missing or changed implementation fails closed instead of silently trading an unreviewed rule.",
      "Account safeguards then check the session cutoff, daily lock, concurrent-position cap, same-ticker position guard, contract liquidity, affordability, and duplicate-order protection.",
      "The AI is passive: it can explain and record context, but it cannot veto or reverse a reviewed V2 setup.",
      "Scanner, setup, contract, order, and broker outcome are separate stages. The UI must show the exact stage and stop reason rather than calling every observed setup a blocked trade.",
    ],
  },
  {
    id: "management",
    emoji: "📊",
    title: "How Open Trades Are Managed",
    body: [
      "An entered V2 trade is linked from setup to selected contract, submission, broker order ID, fill, timed exit, and closed-trade record.",
      "The broker is the source of truth for filled quantity and price. A submitted order is not counted as a position until Alpaca confirms a fill.",
      "If a paper limit order does not fill, cancellation must reach a terminal broker state before any replacement order is allowed. A partial fill reduces the replacement quantity instead of duplicating the position.",
      "Each reviewed strategy keeps its registered same-contract timed exit: 30 minutes for the two SPY rules and 90 minutes for the two TSLA rules.",
      "The hard 3:55 PM session cutoff and account protection remain above every strategy-specific exit.",
    ],
  },
  {
    id: "exits",
    emoji: "🏁",
    title: "The Exit Priority Order",
    body: [
      "Account-level safety exits take priority over the strategy timer: emergency close, daily protection, and the 3:55 PM session cutoff cannot be bypassed by a lesson rule.",
      "If no account-level protection fires, the strategy exits the exact selected contract at its registered horizon using the broker-side executable price.",
      "Trend Continuation and Afternoon Fair Value Gap use 30 minutes. Opening-Range Pullback and Two-Leg Trend Pullback use 90 minutes.",
      "MFE and MAE are measurements of what happened while the trade was open; they are not substitute fills and do not rewrite the exit after the fact.",
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

export function Playbooks() {
  const { user } = useAuth();
  const [params, setParams] = useSearchParams();
  const tab = params.get('tab') ?? 'playbooks';
  const setTab = (value: string) => setParams({tab: value});
  const [search,        setSearch]        = useState("");
  const [activeCategory, setActiveCategory] = useState<string | null>(null);
  const [openSection,   setOpenSection]   = useState<string | null>("routine");   // first section open by default
  const { data: strategyCatalog } = useQuery({ queryKey: ["strategy-catalog", user?.user_id], queryFn: api.settings.strategies });
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
      {params.has('strategy') ? <PairLearning strategyCatalog={strategyCatalog?.strategies ?? []} /> : <>
      {/* Tab bar */}
      <div className="flex gap-2 border-b pb-2" style={{ borderColor: "var(--border)" }}>
        {(["playbooks", "foundations", "glossary", "log-guide", "how-it-works"] as const).map((t) => (
          <button
            key={t}
            className={`btn btn-sm ${tab === t ? "btn-primary" : "btn-ghost"}`}
            onClick={() => setTab(t)}
          >
            {t === "foundations" ? "Chart basics" : t === "playbooks" ? "Learning Hub" : t === "glossary" ? "Trading Glossary" : t === "log-guide" ? "Log Dictionary" : "How It Works"}
          </button>
        ))}
      </div>
      {tab === 'foundations' && <Foundations />}
      {tab === 'glossary' && <section className="card p-5"><h2 className="text-xl font-semibold mb-4">Trading concepts</h2><dl className="space-y-4">{['VWAP','FVG','ATR','RSI','MACD','SMA','EMA','RVOL'].map(term => <div key={term}><dt className="font-semibold">{term}</dt><dd className="text-sm mt-1">{GLOSSARY[term]}</dd></div>)}</dl></section>}
      {tab === 'playbooks' && <EnabledLearningPairs strategies={strategyCatalog?.strategies ?? []} />}

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
      </>}
    </div>
  );
}
