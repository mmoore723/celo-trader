import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import type { Trade } from "../lib/api";
import { formatSignedCurrency } from "../lib/money.js";

type Row = Trade & {
  mode: "paper" | "live";
  journal_key: string; user_id: string; username: string; retained_user: boolean;
  broker_account_id?: string; strategy_version?: string; strategy_name?: string; entry_reason?: string;
  entry_order_id?: string; exit_order_id?: string; entry_fill_time?: string; exit_fill_time?: string;
  parent_trade_id?: number; mode_warning?: string;
};
type Journal = { trades: Row[]; users: { user_id: string; username: string }[];
  strategies: { id: string; name: string }[];
  total: number; has_more: boolean; warnings: string[] };
const missing = "Not recorded";
const money = (value?: number | null) => value == null ? missing : `$${value.toFixed(2)}`;
function time(value?: string | null) {
  if (!value) return missing;
  if (!/(Z|[+-]\d{2}:?\d{2})$/i.test(value)) return value.replace("T", " ").slice(0, 19) + " ET";
  return new Date(value).toLocaleString("en-US", { timeZone: "America/New_York" }) + " ET";
}

export function AdminTradeJournal() {
  const [user, setUser] = useState("");
  const [mode, setMode] = useState("all");
  const [status, setStatus] = useState("all");
  const [ticker, setTicker] = useState("");
  const [strategy, setStrategy] = useState("");
  const [offset, setOffset] = useState(0);
  const [expanded, setExpanded] = useState<string | null>(null);
  const query = useQuery<Journal>({
    queryKey: ["admin-trade-journal", user, mode, status, ticker, strategy, offset],
    queryFn: async ({ signal }) => {
      const params = new URLSearchParams({ user_id: user, mode, status, ticker, strategy_group: strategy, offset: String(offset), limit: "50" });
      const response = await fetch(`/api/admin/trade-journal?${params}`, { credentials: "include", signal });
      if (!response.ok) throw new Error(response.status === 403 ? "Admin access required." : "Journal could not load. Please refresh.");
      return response.json();
    },
    staleTime: 15_000, retry: false,
  });
  function change(set: (value: string) => void, value: string) { set(value); setOffset(0); setExpanded(null); }
  return <section className="card p-3 min-w-0" aria-label="All-user trade journal">
    <div className="flex items-center justify-between gap-2">
      <h3 className="font-semibold">Full trade journal</h3>
      <button className="btn btn-ghost" disabled={query.isFetching} onClick={() => void query.refetch()}>Refresh journal</button>
    </div>
    <p className="text-xs mt-1" style={{ color: "var(--ink-muted)" }}>
      All users and saved broker accounts, including previous accounts. User identifies the journal owner, not a verified person who submitted the order.
      Saved trade records only, not hypothetical research. Open trades do not show live marks here.
      Unlinked records have no matching registered user; their original owner is unverified.
      Older journals contain matching entries, so record counts are not unique executions.
    </p>
    <div className="flex flex-wrap gap-3 my-3 text-sm">
      <label>User <select className="input" value={user} onChange={e => change(setUser, e.target.value)}>
        <option value="">All users</option>
        {query.data?.users.map(u => <option key={u.user_id} value={u.user_id}>{u.username}</option>)}
      </select></label>
      <label>Mode <select className="input" value={mode} onChange={e => change(setMode, e.target.value)}>
        <option value="all">Paper and live</option><option value="paper">Paper</option><option value="live">Live</option>
      </select></label>
      <label>Status <select className="input" value={status} onChange={e => change(setStatus, e.target.value)}>
        <option value="all">All trades</option><option value="open">Open</option><option value="closed">Closed</option>
      </select></label>
      <label>Ticker <input className="input" placeholder="All tickers" value={ticker} maxLength={20}
        onChange={e => change(setTicker, e.target.value.trim().toUpperCase())} /></label>
      <label>Strategy <select className="input" value={strategy}
        onChange={e => change(setStrategy, e.target.value)}>
        <option value="">All strategies</option>
        {strategy && !query.data?.strategies.some(s => s.id === strategy) && <option value={strategy}>{strategy}</option>}
        {query.data?.strategies.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
      </select></label>
    </div>
    {query.isError && <p role="alert" style={{ color: "var(--negative)" }}>{query.error.message}</p>}
    {query.isPending && <p role="status">Loading trade journal...</p>}
    {query.data?.warnings.map(w => <p key={w} role="alert" style={{ color: "var(--negative)" }}>{w}</p>)}
    {query.data && <>
      <p className="text-xs mb-2">{query.data.total} matching journal records. Realized P&amp;L is before fees. Expand a trade for its complete details.</p>
      <div className="overflow-auto" style={{ maxHeight: 560 }} tabIndex={0} aria-label="Trade journal table">
        <table className="w-full text-sm text-left"><thead><tr>
          {["Trade", "User", "Mode / account", "Ticker / option", "Strategy", "Quantity", "Entry", "Exit", "Realized P&L", "Status", "Entered (ET)"].map(h => <th className="p-2 whitespace-nowrap" key={h}>{h}</th>)}
        </tr></thead><tbody>{query.data.trades.map(t => <TradeRows key={t.journal_key} trade={t}
          expanded={expanded === t.journal_key} toggle={() => setExpanded(expanded === t.journal_key ? null : t.journal_key)} />)}</tbody></table>
        {query.data.trades.length === 0 && <p className="p-4">No saved trades match these filters.</p>}
      </div>
      <div className="flex items-center justify-between mt-3 text-sm">
        <button className="btn btn-ghost" disabled={offset === 0 || query.isFetching} onClick={() => setOffset(Math.max(0, offset-50))}>Previous</button>
        <span>Page {Math.floor(offset/50)+1}</span>
        <button className="btn btn-ghost" disabled={!query.data.has_more || query.isFetching} onClick={() => setOffset(offset+50)}>Next</button>
      </div>
    </>}
  </section>;
}

function TradeRows({ trade: t, expanded, toggle }: { trade: Row; expanded: boolean; toggle: () => void }) {
  const details = {
    "User ID": t.user_id, "Broker account": t.broker_account_id, "Contract": t.contract_symbol,
    "Strategy ID": t.strategy_id, "Strategy version": t.strategy_version, "Strike": money(t.strike), "Expiration": t.expiry,
    "Entry reason": t.entry_reason, "Exit reason": t.exit_reason, "Exit time": time(t.exit_time),
    "Entry order": t.entry_order_id, "Exit order": t.exit_order_id,
    "Recorded entry fill time": time(t.entry_fill_time), "Recorded exit fill time": time(t.exit_fill_time),
    "Partial-close parent trade": t.parent_trade_id, "Recorded stop reference": money(t.stop_price),
    "Recorded target reference": money(t.target_price), "Recorded peak": money(t.peak_price),
    "Recorded low": money(t.mae_price), "Recap": t.recap,
  };
  return <><tr className="border-t" style={{ borderColor: "var(--border)" }}>
    <td className="p-2"><button className="btn btn-ghost" aria-expanded={expanded} onClick={toggle}>#{t.id} {expanded ? "Hide" : "Details"}</button></td>
    <td className="p-2 font-semibold">{t.username}</td>
    <td className="p-2"><strong>{t.mode.toUpperCase()}</strong><div className="text-xs break-all">{t.broker_account_id || missing}</div></td>
    <td className="p-2 whitespace-nowrap">{t.ticker} {t.option_type?.toUpperCase() || missing}</td>
    <td className="p-2">{t.strategy_name || t.strategy_id?.replace(/^(RESEARCH_|V2_)/, "").replaceAll("_", " ") || missing}</td>
    <td className="p-2">{t.contracts}</td><td className="p-2">{money(t.entry_price)}</td><td className="p-2">{money(t.exit_price)}</td>
    <td className="p-2 whitespace-nowrap">{t.pnl == null ? missing : formatSignedCurrency(t.pnl)}</td>
    <td className="p-2">{t.status}</td><td className="p-2 whitespace-nowrap">{time(t.entry_time)}</td>
  </tr>{expanded && <tr><td colSpan={11} className="p-3" style={{ background: "var(--panel)" }}>
    {t.mode_warning && <p role="alert">{t.mode_warning}</p>}
    <p className="text-xs mb-2">Recorded stop and target references do not prove those levels were enforced. Fill timestamps are shown only when recorded.</p>
    <dl className="grid grid-cols-1 md:grid-cols-3 gap-3">{Object.entries(details).map(([key, value]) => <div key={key}>
      <dt className="text-xs" style={{ color: "var(--ink-muted)" }}>{key}</dt><dd className="break-words">{value ?? missing}</dd>
    </div>)}</dl>
  </td></tr>}</>;
}
