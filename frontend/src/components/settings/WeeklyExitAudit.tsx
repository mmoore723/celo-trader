import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { useAuth } from "../../contexts/AuthContext";
import type { AppSettings } from "../../lib/api";

type Summary = { id: number; ticker: string; strategy: string; version: string; created: string; status: string; recommendation: string };
type Metrics = { setting?: string; trades: number; net: number; win_rate: number; profit_factor: number | null; profit_factor_infinite?: boolean; max_drawdown: number; worst_trade: number };
type Noise = { available: boolean; exceeds_noise: boolean; improvement?: number; total_noise_threshold?: number; combinations?: number; method?: string };
type Audit = {
  ticker: string; strategy: string; version: string; mode: string; status: string; recommendation: string; reason: string;
  trade_count: number; baseline?: Metrics; actual_recorded?: Metrics; top10?: Metrics[]; grid?: Metrics[];
  noise?: Noise; assumptions?: string[]; coverage_issues?: Record<string, string[]>;
  alternatives?: (Metrics & { status?: string })[];
  walk_forward?: { setting: string; train_count: number; test_count: number; train: Metrics; test: Metrics; baseline_train: Metrics; baseline_test: Metrics; holds_out_of_sample: boolean };
};

async function read<T>(path: string): Promise<T> {
  const response = await fetch(`${import.meta.env.VITE_API_URL ?? ""}/api/weekly-exit-audits${path}`, { credentials: "include" });
  if (!response.ok) throw new Error(`Audit unavailable (${response.status})`);
  return response.json();
}
const money = (value?: number) => value == null ? "Unavailable" : value.toLocaleString("en-US", { style: "currency", currency: "USD" });

function Results({ rows }: { rows: Metrics[] }) {
  return <div className="max-w-full overflow-auto max-h-80"><table className="w-full text-xs">
    <thead><tr>{["Setting", "Trades", "Net P&L", "Win %", "PF", "Drawdown", "Worst"].map(h => <th key={h} className="p-2 text-left">{h}</th>)}</tr></thead>
    <tbody>{rows.map((r, i) => <tr key={`${r.setting}-${i}`}>
      <td className="p-2">{r.setting}</td><td>{r.trades}</td><td>{money(r.net)}</td><td>{r.win_rate?.toFixed(2)}</td>
      <td>{r.profit_factor_infinite ? "Infinite" : r.profit_factor?.toFixed(2) ?? "Unavailable"}</td>
      <td>{money(r.max_drawdown)}</td><td>{money(r.worst_trade)}</td>
    </tr>)}</tbody>
  </table></div>;
}

export function WeeklyExitAudit({ strategyId, version }: { strategyId: string; version?: string }) {
  const context = useContext(AuditContext);
  if (!context) return null;
  const rows = context.audits.filter(r => r.strategy === strategyId && r.version === version);
  const other = context.audits.filter(r => r.strategy === strategyId && r.version !== version);
  const badge = (row: Summary) => <button key={row.id} type="button" className="btn btn-ghost text-xs my-1 max-w-full whitespace-normal text-left"
    onClick={() => context.select(row.id)}>
    Exit audit · {row.ticker} · {row.status === "INCOMPLETE" ? "Needs data" : row.recommendation === "PROPOSE CHANGE" ? "Review suggestion" : "Keep baseline"}
  </button>;
  return <div className="text-xs py-1">
    {context.error ? <button type="button" onClick={context.retry}>Weekly audit unavailable. Retry</button>
      : context.pending ? <span>Weekly audit: loading saved status</span>
      : rows.length ? rows.map(badge) : <span>Weekly Exit Audit: no saved audit for this version</span>}
    {!!other.length && <details><summary>Other code versions ({other.length} separate buckets)</summary>
      {other.map(row => <div key={row.id}><span>{row.version}: </span>{badge(row)}</div>)}</details>}
  </div>;
}

const AuditContext = createContext<{
  audits: Summary[]; pending: boolean; error: boolean; retry: () => void; select: (id: number) => void;
} | null>(null);

export function WeeklyExitAuditProvider({ settings, children }: { settings?: AppSettings; children: ReactNode }) {
  const { user } = useAuth();
  const scope = `${user?.user_id ?? user?.email}:${settings?.active_broker_account_id}:${settings?.paper_trading}`;
  const summaries = useQuery({ queryKey: ["weekly-exit-audits", scope],
    queryFn: () => read<{ audits: Summary[] }>(""), enabled: !!user && !!settings,
    staleTime: 300000, placeholderData: undefined });
  const [selected, setSelected] = useState<number | null>(null);
  useEffect(() => { setSelected(null); }, [scope]);
  return <AuditContext.Provider value={{ audits: summaries.data?.audits ?? [],
    pending: summaries.isPending, error: summaries.isError, retry: () => { void summaries.refetch(); }, select: setSelected }}>
    {children}
    {selected !== null && <AuditDialog key={`${scope}:${selected}`} scope={scope} selected={selected} onClose={() => setSelected(null)} />}
  </AuditContext.Provider>;
}

function AuditDialog({ scope, selected, onClose }: { scope: string; selected: number; onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [showGrid, setShowGrid] = useState(false);
  const detail = useQuery({ queryKey: ["weekly-exit-audit-detail", scope, selected],
    queryFn: () => read<Audit>(`/${selected}`), staleTime: 300000, placeholderData: undefined });
  useEffect(() => { const node = dialog.current; node?.showModal(); return () => node?.close(); }, []);
  const result = detail.data;
  return <dialog ref={dialog} onClose={onClose}
      aria-label="Weekly exit audit results" className="weekly-exit-dialog rounded-xl p-5 w-[min(720px,95vw)] max-h-[85dvh] overflow-auto"
      style={{ background: "var(--surface)", color: "var(--ink)", border: "1px solid var(--border)" }}>
      <div className="flex justify-between gap-4"><h2 className="font-semibold text-lg">Weekly Exit Audit</h2>
        <button type="button" className="btn btn-ghost" onClick={() => dialog.current?.close()}>Close</button></div>
      {detail.isPending ? <p role="status">Loading saved audit...</p> : detail.isError ? <p role="alert">Could not load audit. <button onClick={() => detail.refetch()}>Retry</button></p>
        : result && <div className="space-y-4">
          <p className="text-sm break-words">{result.ticker} · {result.version} · {result.mode} · {result.trade_count} trades</p>
          <div className="rounded-lg p-3" style={{ background: "var(--muted)" }}>
            <strong>{result.status === "INCOMPLETE" ? "Not enough data to compare exits" : result.recommendation === "PROPOSE CHANGE" ? "Review suggested change" : "Keep current exit"}</strong>
            <p className="text-sm mt-1">{result.reason}</p>
          </div>
          <p className="text-xs">Read-only analysis. No trading changes.</p>
          <Results rows={[
            ...(result.actual_recorded ? [{ ...result.actual_recorded, setting: "Recorded journal P&L" }] : []),
            ...(result.baseline ? [{ ...result.baseline, setting: "Hypothetical $65 / 35%" }] : []),
            ...(result.top10 ?? []).slice(0, 1),
          ]} />
          {!result.baseline && <p>Baseline replay unavailable. Missing evidence is not treated as zero P&L.</p>}
          <details><summary className="cursor-pointer font-medium">Validation and candidate results</summary>
          <h3 className="font-semibold mt-3">Chronological 70/30 test</h3>
          {result.walk_forward ? <>
            <p>Training-selected {result.walk_forward.setting}; {result.walk_forward.train_count} train / {result.walk_forward.test_count} test.
              {result.walk_forward.holds_out_of_sample ? " Clears test noise and constraints." : " Does not establish an out-of-sample improvement."}</p>
            <Results rows={[
              { ...result.walk_forward.baseline_train, setting: "Train baseline" },
              { ...result.walk_forward.train, setting: "Train selected" },
              { ...result.walk_forward.baseline_test, setting: "Test baseline" },
              { ...result.walk_forward.test, setting: "Test selected" },
            ]} /></> : <p>Insufficient replay evidence or no qualifying training setting.</p>}
          <h3 className="font-semibold">Noise assessment</h3>
          {result.noise?.available ? <p>Improvement {money(result.noise.improvement)}; noise threshold {money(result.noise.total_noise_threshold)}.
            {result.noise.exceeds_noise ? " Exceeds estimated noise." : " Does not exceed estimated noise."}<br />{result.noise.method}</p>
            : <p>Cannot estimate noise from the available paired results.</p>}
          <h3 className="font-semibold">Alternative exit research</h3>
          <Results rows={(result.alternatives ?? []).filter(r => r.status !== "INCOMPLETE")} />
          {(result.alternatives ?? []).filter(r => r.status === "INCOMPLETE").map(r => <p key={r.setting}>{r.setting}: insufficient path coverage</p>)}
          {!!result.top10?.length && <Results rows={result.top10} />}
          </details>
          <details><summary className="cursor-pointer font-medium">Missing data ({Object.keys(result.coverage_issues ?? {}).length} trades)</summary>
            <div className="max-h-60 overflow-auto text-xs break-words">
            {Object.entries(result.coverage_issues ?? {}).map(([id, issues]) => <p key={id}>Trade {id}: {issues.join(", ")}</p>)}
            </div>
          </details>
          <details onToggle={event => setShowGrid(event.currentTarget.open)}><summary>All grid results ({result.grid?.length ?? 0} completely priced configurations)</summary>
            {showGrid && <Results rows={result.grid ?? []} />}</details>
          <details><summary className="cursor-pointer font-medium">Assumptions and limitations</summary>
          <p className="text-xs break-words">{result.strategy} · {result.version}</p>
          <ul className="list-disc pl-5">{result.assumptions?.map(text => <li key={text}>{text}</li>)}</ul>
          </details>
        </div>}
    </dialog>;
}
