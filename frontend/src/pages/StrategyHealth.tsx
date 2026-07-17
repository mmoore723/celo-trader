/**
 * StrategyHealth.tsx — built-in strategy audit dashboard.
 *
 * Replaces "I write a diag_*.py script, you run it on EC2, screenshot the
 * terminal" with a page that always has the latest answer: for each
 * strategy, how many raw signals fired, how many survived the router's
 * gates, and how many became real trades with what P&L. Runs automatically
 * once/day (trading/loop.py); the button here triggers an on-demand re-run.
 */
import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { RefreshCw, Sparkles, AlertTriangle } from "lucide-react";
import { api, type StrategyFunnelRow } from "../lib/api";
import { PageLoader } from "../components/PageLoader";

const STRAT_NAMES: Record<string, string> = {
  INST_ORB:   "Opening Range Breakout",
  VWAP_PB:    "VWAP Pullback",
  FVG:        "Fair Value Gap",
  IFVG:       "Inverted Fair Value Gap",
  MID_BRK:    "Mid-Day Breakdown",
  AFT_REV:    "Afternoon Reversal",
  TREND_CONT: "Trend Continuation",
};

function pct(n: number, d: number): string {
  return d > 0 ? `${Math.round((n / d) * 100)}%` : "—";
}

function FunnelTable({ perStrategy }: { perStrategy: Record<string, StrategyFunnelRow> }) {
  const rows = Object.entries(perStrategy).sort((a, b) => b[1].raw_signals - a[1].raw_signals);
  if (rows.length === 0) {
    return <p style={{ color: "var(--ink-muted)", fontSize: 13 }}>No raw signals found from any strategy that day.</p>;
  }
  return (
    <div style={{ overflowX: "auto" }}>
      <table className="w-full text-sm" style={{ borderCollapse: "collapse" }}>
        <thead>
          <tr style={{ borderBottom: "1px solid var(--border)", color: "var(--ink-muted)", textAlign: "left" }}>
            <th style={{ padding: "6px 8px" }}>Strategy</th>
            <th style={{ padding: "6px 8px" }}>Raw signals</th>
            <th style={{ padding: "6px 8px" }}>Survived router</th>
            <th style={{ padding: "6px 8px" }}>Actual trades</th>
            <th style={{ padding: "6px 8px" }}>Win rate</th>
            <th style={{ padding: "6px 8px" }}>P&L</th>
            <th style={{ padding: "6px 8px" }}>Fwd-move quality (raw / survivors)</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(([sid, row]) => {
            const flagGated  = row.raw_signals >= 5 && row.router_survivors === 0;
            const flagStuck  = row.router_survivors >= 3 && row.actual_trades === 0;
            return (
              <tr key={sid} style={{ borderBottom: "1px solid var(--border)" }}>
                <td style={{ padding: "6px 8px", fontWeight: 600 }}>
                  {STRAT_NAMES[sid] ?? sid}
                  <div style={{ fontSize: 11, color: "var(--ink-faint)" }}>{sid}</div>
                </td>
                <td style={{ padding: "6px 8px" }}>{row.raw_signals}</td>
                <td style={{ padding: "6px 8px" }}>
                  {row.router_survivors} ({pct(row.router_survivors, row.raw_signals)})
                  {flagGated && (
                    <span title="Every raw signal was blocked before reaching the router" style={{ marginLeft: 6, color: "#f0883e" }}>
                      <AlertTriangle size={13} style={{ display: "inline" }} />
                    </span>
                  )}
                </td>
                <td style={{ padding: "6px 8px" }}>
                  {row.actual_trades}
                  {flagStuck && (
                    <span title="Signals cleared the router but no trade was recorded" style={{ marginLeft: 6, color: "#f0883e" }}>
                      <AlertTriangle size={13} style={{ display: "inline" }} />
                    </span>
                  )}
                </td>
                <td style={{ padding: "6px 8px" }}>{pct(row.actual_wins, row.actual_trades)}</td>
                <td style={{ padding: "6px 8px", color: row.actual_pnl >= 0 ? "var(--positive)" : "var(--negative)" }}>
                  {row.actual_trades > 0 ? `$${row.actual_pnl.toFixed(2)}` : "—"}
                </td>
                <td style={{ padding: "6px 8px" }}>
                  {pct(row.worked_raw, row.raw_signals)} / {pct(row.worked_survivors, row.router_survivors)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export function StrategyHealth() {
  const qc = useQueryClient();
  const [showHistory, setShowHistory] = useState(false);

  const { data: latest, isLoading } = useQuery({
    queryKey: ["strategy-health-latest"],
    queryFn:  api.strategyHealth.latest,
    staleTime: 60_000,
  });

  const { data: history } = useQuery({
    queryKey: ["strategy-health-history"],
    queryFn:  () => api.strategyHealth.history(30),
    enabled:  showHistory,
  });

  const runNow = useMutation({
    mutationFn: api.strategyHealth.run,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["strategy-health-latest"] });
      qc.invalidateQueries({ queryKey: ["strategy-health-history"] });
    },
  });

  if (isLoading) return <PageLoader label="Strategy Health" />;

  return (
    <div className="p-4 md:p-6 flex flex-col gap-4">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div>
          <h1 className="text-lg font-semibold" style={{ color: "var(--ink)" }}>Strategy Health</h1>
          <p style={{ fontSize: 12, color: "var(--ink-muted)" }}>
            Runs automatically every night after close. Replaces the one-off diagnostic scripts —
            raw signals vs. what survived the router vs. what actually traded.
          </p>
        </div>
        <button
          className="btn btn-primary"
          onClick={() => runNow.mutate()}
          disabled={runNow.isPending}
        >
          <RefreshCw size={14} className={runNow.isPending ? "animate-spin" : ""} />
          {runNow.isPending ? "Running audit…" : "Run Audit Now"}
        </button>
      </div>

      {runNow.isError && (
        <div className="card" style={{ padding: 12, color: "var(--negative)", fontSize: 13 }}>
          Audit failed: {(runNow.error as Error)?.message ?? "unknown error"}
        </div>
      )}

      {(() => {
        const shown = runNow.data ?? latest;
        const agg = shown?.aggregate;
        if (!shown?.available || !agg) {
          return (
            <div className="card" style={{ padding: 20, textAlign: "center", color: "var(--ink-muted)" }}>
              No audit has run yet. It will run automatically tonight after close, or press
              "Run Audit Now" to see today's signal funnel immediately.
            </div>
          );
        }
        return (
            <>
              <div className="card" style={{ padding: 16 }}>
                <div style={{ fontSize: 12, color: "var(--ink-faint)", marginBottom: 8 }}>
                  Audit for {agg.date} — {agg.tickers_scanned.length} ticker(s) scanned:{" "}
                  {agg.tickers_scanned.join(", ") || "none"}
                </div>
                <pre style={{
                  whiteSpace: "pre-wrap", fontFamily: "inherit", fontSize: 13,
                  color: "var(--ink)", margin: 0, lineHeight: 1.5,
                }}>
                  {shown.rule_summary}
                </pre>
              </div>

              {shown.ai_summary && (
                <div className="card" style={{ padding: 16, borderLeft: "3px solid var(--accent)" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 8, color: "var(--accent)" }}>
                    <Sparkles size={14} />
                    <span style={{ fontSize: 12, fontWeight: 600 }}>Claude's take</span>
                  </div>
                  <p style={{ fontSize: 13, color: "var(--ink)", margin: 0, lineHeight: 1.5, whiteSpace: "pre-wrap" }}>
                    {shown.ai_summary}
                  </p>
                </div>
              )}

              <div className="card" style={{ padding: 16 }}>
                <FunnelTable perStrategy={agg.per_strategy} />
              </div>
            </>
        );
      })()}

      <div className="card" style={{ padding: 16 }}>
        <button
          onClick={() => setShowHistory(v => !v)}
          style={{ background: "none", border: "none", cursor: "pointer", padding: 0,
                   fontSize: 13, fontWeight: 600, color: "var(--ink)" }}
        >
          {showHistory ? "Hide" : "Show"} audit history
        </button>
        {showHistory && (
          <div style={{ marginTop: 10, display: "flex", flexDirection: "column", gap: 6 }}>
            {(history?.audits ?? []).length === 0 && (
              <p style={{ fontSize: 12, color: "var(--ink-muted)" }}>No history yet.</p>
            )}
            {(history?.audits ?? []).map(row => (
              <div key={row.audit_date} style={{ fontSize: 12, borderBottom: "1px solid var(--border)", paddingBottom: 6 }}>
                <span style={{ fontWeight: 600, color: "var(--ink)" }}>{row.audit_date}</span>
                <span style={{ color: "var(--ink-faint)", marginLeft: 8 }}>{row.tickers}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
