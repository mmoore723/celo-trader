import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useAuth } from "../../contexts/AuthContext";
import { api } from "../../lib/api";

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
  return <div className="overflow-x-auto"><table className="w-full text-xs">
    <thead><tr>{["Setting", "Trades", "Net P&L", "Win %", "PF", "Drawdown", "Worst"].map(h => <th key={h} className="p-2 text-left">{h}</th>)}</tr></thead>
    <tbody>{rows.map((r, i) => <tr key={`${r.setting}-${i}`}>
      <td className="p-2">{r.setting}</td><td>{r.trades}</td><td>{money(r.net)}</td><td>{r.win_rate?.toFixed(2)}</td>
      <td>{r.profit_factor_infinite ? "Infinite" : r.profit_factor?.toFixed(2) ?? "Unavailable"}</td>
      <td>{money(r.max_drawdown)}</td><td>{money(r.worst_trade)}</td>
    </tr>)}</tbody>
  </table></div>;
}

export function WeeklyExitAudit({ strategyId, version }: { strategyId: string; version?: string }) {
  const { user } = useAuth();
  const { data: settings } = useQuery({ queryKey: ["settings"], queryFn: api.settings.get });
  const scope = `${user?.user_id ?? user?.email}:${settings?.active_broker_account_id}:${settings?.paper_trading}`;
  const summaries = useQuery({ queryKey: ["weekly-exit-audits", scope],
    queryFn: () => read<{ audits: Summary[] }>(""), enabled: !!user && !!settings, staleTime: 60000 });
  const [selected, setSelected] = useState<number | null>(null);
  const dialog = useRef<HTMLDialogElement>(null);
  const detail = useQuery({ queryKey: ["weekly-exit-audit-detail", scope, selected],
    queryFn: () => read<Audit>(`/${selected}`), enabled: selected !== null, staleTime: 60000 });
  useEffect(() => { setSelected(null); dialog.current?.close(); }, [scope]);
  useEffect(() => { if (selected !== null) dialog.current?.showModal(); }, [selected]);
  const rows = summaries.data?.audits.filter(r => r.strategy === strategyId && r.version === version) ?? [];
  const other = summaries.data?.audits.filter(r => r.strategy === strategyId && r.version !== version) ?? [];
  const result = detail.data;
  const badge = (row: Summary) => <button key={row.id} type="button" className="btn btn-ghost text-xs my-1"
    onClick={() => setSelected(row.id)}>
    Weekly Exit Audit: {new Date(row.created).toLocaleDateString()} - {row.ticker} - {row.status === "INCOMPLETE" ? "Data incomplete" : row.recommendation}
  </button>;
  return <div className="text-xs py-1">
    {summaries.isError ? <button type="button" onClick={() => summaries.refetch()}>Weekly audit unavailable. Retry</button>
      : summaries.isPending ? <span>Weekly audit: loading saved status</span>
      : rows.length ? rows.map(badge) : <span>Weekly Exit Audit: no saved audit for this version</span>}
    {!!other.length && <details><summary>Other code versions ({other.length} separate buckets)</summary>
      {other.map(row => <div key={row.id}><span>{row.version}: </span>{badge(row)}</div>)}</details>}
    <dialog ref={dialog} onClose={() => setSelected(null)}
      aria-label="Weekly exit audit results" className="rounded-xl p-5 w-[min(960px,95vw)] max-h-[90vh] overflow-y-auto"
      style={{ background: "var(--surface)", color: "var(--ink)", border: "1px solid var(--border)" }}>
      <div className="flex justify-between gap-4"><h2 className="font-semibold text-lg">Weekly Exit Audit</h2>
        <button type="button" className="btn btn-ghost" onClick={() => dialog.current?.close()}>Close</button></div>
      {detail.isPending ? <p role="status">Loading saved audit...</p> : detail.isError ? <p role="alert">Could not load audit. <button onClick={() => detail.refetch()}>Retry</button></p>
        : result && <div className="space-y-4">
          <p>{result.ticker} · {result.strategy} · {result.version} · {result.mode} · {result.trade_count} accumulated trades</p>
          <p><strong>{result.recommendation}</strong> · {result.status}<br />{result.reason}</p>
          <p>Analysis only. This dialog cannot change an exit or enable trading.</p>
          <Results rows={[
            ...(result.actual_recorded ? [{ ...result.actual_recorded, setting: "Recorded journal P&L" }] : []),
            ...(result.baseline ? [{ ...result.baseline, setting: "Hypothetical $65 / 35%" }] : []),
            ...(result.top10 ?? []),
          ]} />
          {!result.baseline && <p>Baseline replay unavailable. Missing evidence is not treated as zero P&L.</p>}
          <h3 className="font-semibold">Chronological 70/30 test</h3>
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
          <details><summary>Data coverage</summary>
            {Object.entries(result.coverage_issues ?? {}).map(([id, issues]) => <p key={id}>Trade {id}: {issues.join(", ")}</p>)}
          </details>
          <details><summary>All grid results ({result.grid?.length ?? 0} completely priced configurations)</summary>
            <Results rows={result.grid ?? []} /></details>
          <h3 className="font-semibold">What I cannot know from this data</h3>
          <ul className="list-disc pl-5">{result.assumptions?.map(text => <li key={text}>{text}</li>)}</ul>
        </div>}
    </dialog>
  </div>;
}
