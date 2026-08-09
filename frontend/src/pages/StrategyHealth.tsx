/**
 * StrategyHealth.tsx — built-in strategy audit dashboard.
 *
 * Replaces "I write a diag_*.py script, you run it on EC2, screenshot the
 * terminal" with a page that always has the latest answer: for each
 * strategy, how many raw signals fired, how many survived the router's
 * gates, and how many became real trades with what P&L. Runs automatically
 * once/day (trading/loop.py); the button here triggers an on-demand re-run.
 *
 * 2026-07-20: added a Weekly tab. Deliberately the SAME page as the daily
 * audit, not a separate one — a user flagged that two parallel AI summaries
 * (daily funnel vs. a proposed standalone "AI advisor") would just create
 * confusion about which to trust. The weekly view reuses daily audits
 * already saved plus real closed trades; see strategy_health/weekly.py.
 */
import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { RefreshCw, Sparkles, AlertTriangle } from "lucide-react";
import { api, type AppSettings, type StrategyFunnelRow, type StrategyRiskMathRow, type StrategyScorecard, type CandidateScorecard, type PaperResearchScorecard, type PaidResearchEvidence, type V2OrbPaperScorecard } from "../lib/api";
import { PageLoader } from "../components/PageLoader";

const STRAT_NAMES: Record<string, string> = {
  INST_ORB:   "Opening Range Breakout",
  VWAP_PB:    "VWAP Pullback",
  FVG:        "Fair Value Gap",
  IFVG:       "Inverted Fair Value Gap",
  MID_BRK:    "Mid-Day Breakdown",
  AFT_REV:    "Afternoon Reversal",
  TREND_CONT: "Trend Continuation",
  V2_ORB_PULLBACK: "TSLA Opening-Range Pullback",
};

function ActivePilotCard({ settings }: { settings?: AppSettings }) {
  const enabled = settings?.strategy_orb_pullback_v2_enabled
    && settings.validated_strategy_ids?.includes("V2_ORB_PULLBACK");
  if (!enabled) {
    return <div className="card" style={{ padding: 16, borderLeft: "3px solid var(--ink-faint)" }}>
      <h2 className="text-sm font-semibold" style={{ marginBottom: 6 }}>What the bot is testing now</h2>
      <p style={{ fontSize: 13, color: "var(--ink-muted)", margin: 0 }}>
        No research strategy is currently allowed to place a paper trade. The bot can observe the market, but it will not enter a new position.
      </p>
    </div>;
  }
  return <div className="card" style={{ padding: 16, borderLeft: "3px solid var(--accent)" }}>
    <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", marginBottom: 6 }}>
      <h2 className="text-sm font-semibold" style={{ margin: 0 }}>What the bot is testing now</h2>
      <span style={{ fontSize: 11, fontWeight: 700, color: "var(--positive)", background: "var(--positive-bg)", borderRadius: 999, padding: "2px 8px" }}>PAPER ONLY</span>
    </div>
    <p style={{ fontSize: 13, color: "var(--ink)", margin: "0 0 8px", lineHeight: 1.5 }}>
      <b>TSLA Opening-Range Pullback.</b> The bot marks the first 15 minutes after the open, waits for price to break that range, return to it, and then bounce in the original direction. It only acts after that bounce confirms.
    </p>
    <p style={{ fontSize: 12, color: "var(--ink-muted)", margin: 0, lineHeight: 1.5 }}>
      Contract rule: 7–21 days until expiration, closest out-of-the-money TSLA option, $0.80–$10 ask, and an 8% or tighter spread. A paper trade buys at the seller’s ask and records the same contract’s buyer bid at the 90-minute exit. The journal will show the setup, contract, exit reason, best move (MFE), and worst move (MAE). Positive past results are a candidate—not a promise—so this stays paper-only while it gathers new evidence.
    </p>
  </div>;
}

function pct(n: number, d: number): string {
  return d > 0 ? `${Math.round((n / d) * 100)}%` : "—";
}

function ScorecardTable({ rows }: { rows: StrategyScorecard["strategies"] }) {
  if (!rows.length) return <p style={{ fontSize: 12, color: "var(--ink-muted)" }}>No tagged results yet — opportunity trades will appear separately once entered.</p>;
  return <div style={{ overflowX: "auto" }}><table className="w-full text-sm"><thead><tr><th>Strategy</th><th>Trades</th><th>Win rate</th><th>Expectancy</th><th>P&amp;L</th><th>Blocked</th><th>Status</th></tr></thead><tbody>{rows.map(r => <tr key={r.strategy_id}><td>{STRAT_NAMES[r.strategy_id] ?? r.strategy_id}</td><td>{r.closed_trades}</td><td>{r.win_rate == null ? "—" : `${r.win_rate}%`}</td><td style={{ color: (r.expectancy ?? 0) >= 0 ? "var(--positive)" : "var(--negative)" }}>{r.expectancy == null ? "—" : `$${r.expectancy.toFixed(2)}`}</td><td style={{ color: r.pnl >= 0 ? "var(--positive)" : "var(--negative)" }}>${r.pnl.toFixed(2)}</td><td>{r.blocked_signals}</td><td>{r.sample_status === "review_ready" ? "Ready to review" : "Collecting data"}</td></tr>)}</tbody></table></div>;
}

function Scorecard({ data }: { data: StrategyScorecard }) {
  return <div className="card" style={{ padding: 16 }}><h2 className="text-sm font-semibold" style={{ marginBottom: 8 }}>30-Day Evidence Scorecard</h2>
    <p style={{ fontSize: 12, color: "var(--ink-muted)", marginBottom: 10 }}>“Ready to review” requires {data.minimum_review_trades} closed trades. It means there is enough paper evidence to inspect—not that a strategy is proven profitable. This never changes sizing.</p>
    <ScorecardTable rows={data.strategies} />
    <h3 className="text-sm font-semibold" style={{ margin: "16px 0 6px" }}>Opportunity tier — separate paper evidence</h3>
    <p style={{ fontSize: 12, color: "var(--ink-muted)", marginBottom: 8 }}>These results are never blended into the main tier’s expectancy or sizing evidence.</p>
    <ScorecardTable rows={data.opportunity_strategies ?? []} />
  </div>
}

function CandidateScorecard({ data }: { data: CandidateScorecard }) {
  if (!data.strategies.length) {
    return <div className="card" style={{ padding: 16 }}>
      <h2 className="text-sm font-semibold" style={{ marginBottom: 6 }}>What the gates did</h2>
      <p style={{ fontSize: 13, color: "var(--ink-muted)", margin: 0 }}>
        No new paper candidates have been recorded for this account yet. This starts collecting while the bot evaluates market-session signals.
      </p>
    </div>;
  }
  return <div className="card" style={{ padding: 16 }}>
    <h2 className="text-sm font-semibold" style={{ marginBottom: 6 }}>What the gates did</h2>
    <p style={{ fontSize: 12, color: "var(--ink-muted)", marginBottom: 10 }}>
      Every setup the router evaluated in the last {data.days} days is counted here. “Blocked” is not a loss—it only means the bot did not take it. {data.note}
    </p>
    <div style={{ overflowX: "auto" }}><table className="w-full text-sm"><thead><tr><th>Strategy</th><th>Setups seen</th><th>Entered</th><th>Blocked</th><th>60-min direction</th><th>Avg move</th><th>Top reason blocked</th></tr></thead><tbody>
      {data.strategies.map(row => {
        const top = Object.entries(row.block_reasons).sort((a, b) => b[1] - a[1])[0];
        const direction = row.directional_win_rate == null ? "Collecting" : `${row.directional_win_rate}% (${row.measured})`;
        const avgMove = row.avg_directional_move_pct == null ? "—" : `${row.avg_directional_move_pct >= 0 ? "+" : ""}${row.avg_directional_move_pct.toFixed(2)}%`;
        return <tr key={row.strategy_id}><td>{STRAT_NAMES[row.strategy_id] ?? row.strategy_id}</td><td>{row.raw_candidates}</td><td>{row.entered}</td><td>{row.blocked}</td><td>{direction}</td><td style={{ color: (row.avg_directional_move_pct ?? 0) >= 0 ? "var(--positive)" : "var(--negative)" }}>{avgMove}</td><td>{top ? `${top[0]} (${top[1]})` : "—"}</td></tr>;
      })}
    </tbody></table></div>
  </div>;
}

function QQQResearchCard({ data }: { data: PaperResearchScorecard }) {
  const result = data.avg_executable_return_pct == null ? "Collecting quotes" :
    `${data.avg_executable_return_pct >= 0 ? "+" : ""}${data.avg_executable_return_pct.toFixed(2)}%`;
  const underlying = data.avg_underlying_move_pct == null ? "—" :
    `${data.avg_underlying_move_pct >= 0 ? "+" : ""}${data.avg_underlying_move_pct.toFixed(2)}%`;
  return <div className="card" style={{ padding: 16, borderLeft: "3px solid var(--accent)" }}>
    <h2 className="text-sm font-semibold" style={{ marginBottom: 6 }}>QQQ paper experiment — not a bot strategy</h2>
    <p style={{ fontSize: 12, color: "var(--ink-muted)", marginBottom: 12 }}>
      When QQQ falls at least 0.25% in the first 30 minutes, this records a put quote near 10:00 AM and the same contract near 3:55 PM. It never sends an order, changes sizing, or affects the main bot.
    </p>
    <div style={{ display: "flex", gap: 24, flexWrap: "wrap", fontSize: 13 }}>
      <span><b>{data.observations}</b> signals observed</span>
      <span><b>{data.quote_measured}</b> quote-to-quote results</span>
      <span>Option result: <b style={{ color: (data.avg_executable_return_pct ?? 0) >= 0 ? "var(--positive)" : "var(--negative)" }}>{result}</b></span>
      <span>Underlying move: <b>{underlying}</b></span>
      <span>Win rate: <b>{data.option_win_rate_pct == null ? "—" : `${data.option_win_rate_pct}%`}</b></span>
    </div>
    <p style={{ fontSize: 11, color: "var(--ink-faint)", margin: "10px 0 0" }}>{data.note}</p>
  </div>;
}

function PaidTslaResearchCard({ data }: { data: PaidResearchEvidence }) {
  const fmt = (value: number) => `${value >= 0 ? "+" : ""}${value.toFixed(2)}%`;
  return <div className="card" style={{ padding: 16, borderLeft: "3px solid var(--accent)" }}>
    <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", marginBottom: 6 }}>
      <h2 className="text-sm font-semibold" style={{ margin: 0 }}>What we learned from real option prices</h2>
      <span style={{ fontSize: 11, fontWeight: 700, color: "var(--accent)", background: "var(--accent-bg)", borderRadius: 999, padding: "2px 8px" }}>HISTORICAL RESEARCH</span>
    </div>
    <p style={{ fontSize: 13, color: "var(--ink)", margin: "0 0 10px", lineHeight: 1.5 }}>
      <b>{data.label}.</b> {data.execution_model}
    </p>
    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 10 }}>
      <div style={{ padding: 10, border: "1px solid var(--border)", borderRadius: 8 }}>
        <div style={{ fontSize: 11, color: "var(--ink-muted)" }}>Whole paid study</div>
        <div style={{ fontWeight: 700, fontSize: 17, color: "var(--positive)" }}>{fmt(data.baseline.average_return_pct)}</div>
        <div style={{ fontSize: 12, color: "var(--ink-muted)" }}>{data.baseline.measured_signals} setups · {data.baseline.win_rate_pct}% positive</div>
      </div>
      <div style={{ padding: 10, border: "1px solid var(--border)", borderRadius: 8 }}>
        <div style={{ fontSize: 11, color: "var(--ink-muted)" }}>Unseen later dates</div>
        <div style={{ fontWeight: 700, fontSize: 17, color: "var(--positive)" }}>{fmt(data.unseen_holdout.average_return_pct)}</div>
        <div style={{ fontSize: 12, color: "var(--ink-muted)" }}>{data.unseen_holdout.measured_signals} setups · {data.unseen_holdout.win_rate_pct}% positive</div>
      </div>
      <div style={{ padding: 10, border: "1px solid var(--border)", borderRadius: 8 }}>
        <div style={{ fontSize: 11, color: "var(--ink-muted)" }}>Honest month-by-month check</div>
        <div style={{ fontWeight: 700, fontSize: 17, color: "var(--positive)" }}>{fmt(data.walkforward.baseline.average_return_pct)}</div>
        <div style={{ fontSize: 12, color: "var(--ink-muted)" }}>baseline beat best-past tweak: {fmt(data.walkforward.best_past_variant.average_return_pct)}</div>
      </div>
    </div>
    <p style={{ fontSize: 12, color: "var(--ink-muted)", margin: "10px 0 0", lineHeight: 1.5 }}><b>Decision:</b> {data.what_changed}</p>
    <div style={{ marginTop: 12, padding: 12, background: "var(--surface-muted, rgba(0,0,0,.025))", borderRadius: 8 }}>
      <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 6 }}>How a future paper trade will work</div>
      <p style={{ fontSize: 12, color: "var(--ink-muted)", margin: "0 0 5px", lineHeight: 1.5 }}><b>1. Contract:</b> {data.paper_pilot.contract_rule}</p>
      <p style={{ fontSize: 12, color: "var(--ink-muted)", margin: "0 0 5px", lineHeight: 1.5 }}><b>2. Exit:</b> {data.paper_pilot.exit_rule}</p>
      <p style={{ fontSize: 12, color: "var(--ink-muted)", margin: 0, lineHeight: 1.5 }}><b>Why this matters:</b> {data.paper_pilot.why}</p>
    </div>
    <div style={{ marginTop: 12 }}>
      <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 6 }}>Why VWAP and EMA are not automatic exits</div>
      <p style={{ fontSize: 12, color: "var(--ink-muted)", margin: "0 0 8px" }}>{data.exit_comparison.label}</p>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))", gap: 8 }}>
        {[
          ["90-minute baseline", data.exit_comparison.fixed_90m],
          ["VWAP-loss exit", data.exit_comparison.vwap_loss],
          ["EMA-9-loss exit", data.exit_comparison.ema9_loss],
        ].map(([label, result]) => {
          const row = result as { average_return_pct: number; measured_signals: number };
          return <div key={label as string} style={{ padding: 9, border: "1px solid var(--border)", borderRadius: 8 }}>
            <div style={{ fontSize: 11, color: "var(--ink-muted)" }}>{label as string}</div>
            <div style={{ fontWeight: 700, color: row.average_return_pct >= 0 ? "var(--positive)" : "var(--negative)" }}>{fmt(row.average_return_pct)}</div>
            <div style={{ fontSize: 11, color: "var(--ink-muted)" }}>{row.measured_signals} later-date setups</div>
          </div>;
        })}
      </div>
      <p style={{ fontSize: 12, color: "var(--ink-muted)", margin: "8px 0 0", lineHeight: 1.5 }}>{data.exit_comparison.conclusion}</p>
    </div>
    <p style={{ fontSize: 12, color: "var(--warning, #b45309)", margin: "6px 0 0", lineHeight: 1.5 }}>
      <b>How certain is this?</b> {data.uncertainty.label}: {fmt(data.uncertainty.low_pct)} to {fmt(data.uncertainty.high_pct)}. {data.uncertainty.interpretation}
    </p>
    <p style={{ fontSize: 12, color: "var(--ink-muted)", margin: "6px 0 0", lineHeight: 1.5 }}><b>Next:</b> {data.next_step}</p>
    <p style={{ fontSize: 11, color: "var(--ink-faint)", margin: "8px 0 0", lineHeight: 1.45 }}>{data.caveat}</p>
  </div>;
}

function V2OrbProspectiveCard({ data }: { data: V2OrbPaperScorecard }) {
  const returnText = data.average_return_pct == null ? "Collecting" : `${data.average_return_pct >= 0 ? "+" : ""}${data.average_return_pct.toFixed(2)}%`;
  const ready = data.sample_status === "review_ready";
  return <div className="card" style={{ padding: 16, borderLeft: `3px solid ${ready ? "var(--positive)" : "var(--accent)"}` }}>
    <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", marginBottom: 6 }}>
      <h2 className="text-sm font-semibold" style={{ margin: 0 }}>TSLA V2 paper evidence</h2>
      <span style={{ fontSize: 11, fontWeight: 700, borderRadius: 999, padding: "2px 8px", color: ready ? "var(--positive)" : "var(--accent)", background: ready ? "var(--positive-bg)" : "var(--accent-bg)" }}>
        {ready ? "READY TO REVIEW" : "COLLECTING"}
      </span>
    </div>
    <p style={{ fontSize: 12, color: "var(--ink-muted)", margin: "0 0 10px", lineHeight: 1.5 }}>
      This is kept separate from every older strategy and from historical research. It only counts the currently selected broker account’s V2 paper trades.
    </p>
    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(120px, 1fr))", gap: 8 }}>
      <div><div style={{ fontSize: 11, color: "var(--ink-muted)" }}>Closed / needed</div><b>{data.closed_trades} / {data.minimum_review_trades}</b></div>
      <div><div style={{ fontSize: 11, color: "var(--ink-muted)" }}>Win rate</div><b>{data.win_rate_pct == null ? "—" : `${data.win_rate_pct}%`}</b></div>
      <div><div style={{ fontSize: 11, color: "var(--ink-muted)" }}>Average return</div><b style={{ color: (data.average_return_pct ?? 0) >= 0 ? "var(--positive)" : "var(--negative)" }}>{returnText}</b></div>
      <div><div style={{ fontSize: 11, color: "var(--ink-muted)" }}>Matching 90-min exits</div><b>{data.study_matched_exits}</b></div>
    </div>
    {data.open_trades > 0 && <p style={{ fontSize: 12, color: "var(--ink-muted)", margin: "10px 0 0" }}>{data.open_trades} paper trade{data.open_trades === 1 ? " is" : "s are"} still waiting for its 90-minute result.</p>}
    {data.nonmatching_exits > 0 && <p style={{ fontSize: 12, color: "var(--warning, #b45309)", margin: "10px 0 0" }}>⚠ {data.nonmatching_exits} closed trade{data.nonmatching_exits === 1 ? " did" : "s did"} not use the studied 90-minute exit, so those results are not treated as matching study evidence.</p>}
    <p style={{ fontSize: 11, color: "var(--ink-faint)", margin: "10px 0 0" }}>{data.note}</p>
  </div>;
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

function RiskMathTable({ perStrategy }: { perStrategy: Record<string, StrategyRiskMathRow> }) {
  const rows = Object.entries(perStrategy).sort((a, b) => b[1].n - a[1].n);
  if (rows.length === 0) {
    return <p style={{ color: "var(--ink-muted)", fontSize: 13 }}>No closed trades in this window.</p>;
  }
  return (
    <div style={{ overflowX: "auto" }}>
      <table className="w-full text-sm" style={{ borderCollapse: "collapse" }}>
        <thead>
          <tr style={{ borderBottom: "1px solid var(--border)", color: "var(--ink-muted)", textAlign: "left" }}>
            <th style={{ padding: "6px 8px" }}>Strategy</th>
            <th style={{ padding: "6px 8px" }}>Trades</th>
            <th style={{ padding: "6px 8px" }}>Win rate</th>
            <th style={{ padding: "6px 8px" }}>Avg P&L</th>
            <th style={{ padding: "6px 8px" }}>Total P&L</th>
            <th style={{ padding: "6px 8px" }}>Realized win:loss</th>
            <th style={{ padding: "6px 8px" }}>Top exit reasons</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(([sid, row]) => {
            const topReasons = Object.entries(row.exit_reasons)
              .sort((a, b) => b[1] - a[1]).slice(0, 2)
              .map(([r, n]) => `${r} (${n})`).join(", ");
            return (
              <tr key={sid} style={{ borderBottom: "1px solid var(--border)" }}>
                <td style={{ padding: "6px 8px", fontWeight: 600 }}>
                  {STRAT_NAMES[sid] ?? sid}
                  <div style={{ fontSize: 11, color: "var(--ink-faint)" }}>{sid}</div>
                </td>
                <td style={{ padding: "6px 8px" }}>
                  {row.n}
                  {row.n < 10 && (
                    <span title="Sample under 10 trades — read cautiously" style={{ marginLeft: 6, color: "#f0883e" }}>
                      <AlertTriangle size={13} style={{ display: "inline" }} />
                    </span>
                  )}
                </td>
                <td style={{ padding: "6px 8px" }}>{row.win_rate_pct.toFixed(0)}%</td>
                <td style={{ padding: "6px 8px", color: row.avg_pnl >= 0 ? "var(--positive)" : "var(--negative)" }}>
                  ${row.avg_pnl.toFixed(2)}
                </td>
                <td style={{ padding: "6px 8px", color: row.total_pnl >= 0 ? "var(--positive)" : "var(--negative)" }}>
                  ${row.total_pnl.toFixed(2)}
                </td>
                <td style={{ padding: "6px 8px" }}>
                  {row.realized_rr != null ? `${row.realized_rr}x` : "—"}
                </td>
                <td style={{ padding: "6px 8px", fontSize: 12, color: "var(--ink-muted)" }}>
                  {topReasons || "—"}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function DailyView() {
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
  const { data: scorecard } = useQuery({ queryKey: ["strategy-health-scorecard"], queryFn: () => api.strategyHealth.scorecard(30), staleTime: 60_000 });
  const { data: candidateScorecard } = useQuery({ queryKey: ["strategy-health-candidate-scorecard"], queryFn: () => api.strategyHealth.candidateScorecard(30), staleTime: 60_000 });
  const { data: qqqResearch } = useQuery({ queryKey: ["strategy-health-qqq-paper-research"], queryFn: api.strategyHealth.qqqOpeningResearch, staleTime: 60_000 });
  const { data: paidTslaResearch } = useQuery({ queryKey: ["strategy-health-paid-tsla-v2-orb"], queryFn: api.strategyHealth.paidTslaV2Orb, staleTime: 60_000 });
  const { data: v2OrbPaper } = useQuery({ queryKey: ["strategy-health-v2-orb-paper"], queryFn: api.strategyHealth.v2OrbPaperScorecard, staleTime: 60_000 });
  const { data: settings } = useQuery({ queryKey: ["settings"], queryFn: api.settings.get, staleTime: 60_000 });

  const runNow = useMutation({
    mutationFn: api.strategyHealth.run,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["strategy-health-latest"] });
      qc.invalidateQueries({ queryKey: ["strategy-health-history"] });
    },
  });

  if (isLoading) return <PageLoader label="Strategy Health" />;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <p style={{ fontSize: 12, color: "var(--ink-muted)" }}>
          Runs automatically every night after close. Raw signals vs. what survived the router
          vs. what actually traded, for the most recent trading day.
        </p>
        <button
          className="btn btn-primary"
          onClick={() => runNow.mutate()}
          disabled={runNow.isPending}
        >
          <RefreshCw size={14} className={runNow.isPending ? "animate-spin" : ""} />
          {runNow.isPending ? "Running audit…" : "Run Audit Now"}
        </button>
      </div>
      <ActivePilotCard settings={settings} />
      {paidTslaResearch && <PaidTslaResearchCard data={paidTslaResearch} />}
      {v2OrbPaper && <V2OrbProspectiveCard data={v2OrbPaper} />}
      {scorecard && <Scorecard data={scorecard} />}
      {candidateScorecard && <CandidateScorecard data={candidateScorecard} />}
      {qqqResearch && <QQQResearchCard data={qqqResearch} />}

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

function WeeklyView() {
  const qc = useQueryClient();
  const [showHistory, setShowHistory] = useState(false);

  const { data: latest, isLoading } = useQuery({
    queryKey: ["strategy-health-weekly-latest"],
    queryFn:  api.strategyHealth.weeklyLatest,
    staleTime: 60_000,
  });

  const { data: history } = useQuery({
    queryKey: ["strategy-health-weekly-history"],
    queryFn:  () => api.strategyHealth.weeklyHistory(12),
    enabled:  showHistory,
  });

  const runNow = useMutation({
    mutationFn: api.strategyHealth.weeklyRun,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["strategy-health-weekly-latest"] });
      qc.invalidateQueries({ queryKey: ["strategy-health-weekly-history"] });
    },
  });

  if (isLoading) return <PageLoader label="Weekly Review" />;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <p style={{ fontSize: 12, color: "var(--ink-muted)" }}>
          Runs automatically every Friday after close. Rolls up the trailing week's daily audits
          plus real closed trades — win rate, exit-reason mix, realized win:loss vs. the R:R
          gate. The AI take here is specifically asked for one concrete, testable recommendation,
          not a summary — and it will say so plainly if the sample is still too thin to trust.
        </p>
        <button
          className="btn btn-primary"
          onClick={() => runNow.mutate()}
          disabled={runNow.isPending}
        >
          <RefreshCw size={14} className={runNow.isPending ? "animate-spin" : ""} />
          {runNow.isPending ? "Running review…" : "Run Weekly Review Now"}
        </button>
      </div>

      {runNow.isError && (
        <div className="card" style={{ padding: 12, color: "var(--negative)", fontSize: 13 }}>
          Weekly review failed: {(runNow.error as Error)?.message ?? "unknown error"}
        </div>
      )}

      {(() => {
        const shown = runNow.data ?? latest;
        const agg = shown?.aggregate;
        if (!shown?.available || !agg) {
          return (
            <div className="card" style={{ padding: 20, textAlign: "center", color: "var(--ink-muted)" }}>
              No weekly review yet. It will run automatically this Friday after close, or press
              "Run Weekly Review Now" to see the trailing week's picture immediately.
            </div>
          );
        }
        return (
            <>
              <div className="card" style={{ padding: 16 }}>
                <div style={{ fontSize: 12, color: "var(--ink-faint)", marginBottom: 8 }}>
                  {agg.week_label} — {agg.daily_audits_included.length} daily audit(s) rolled up
                  over the trailing {agg.window_days} days.
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
                    <span style={{ fontSize: 12, fontWeight: 600 }}>Claude's recommendation</span>
                  </div>
                  <p style={{ fontSize: 13, color: "var(--ink)", margin: 0, lineHeight: 1.5, whiteSpace: "pre-wrap" }}>
                    {shown.ai_summary}
                  </p>
                </div>
              )}

              <div className="card" style={{ padding: 16 }}>
                <h3 className="text-sm font-semibold mb-3" style={{ color: "var(--ink)" }}>
                  Real-trade risk math (this window)
                </h3>
                <RiskMathTable perStrategy={agg.per_strategy_risk_math} />
              </div>

              <div className="card" style={{ padding: 16 }}>
                <h3 className="text-sm font-semibold mb-3" style={{ color: "var(--ink)" }}>
                  Signal funnel (summed across the week)
                </h3>
                <FunnelTable perStrategy={agg.per_strategy_funnel} />
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
          {showHistory ? "Hide" : "Show"} weekly history
        </button>
        {showHistory && (
          <div style={{ marginTop: 10, display: "flex", flexDirection: "column", gap: 6 }}>
            {(history?.audits ?? []).length === 0 && (
              <p style={{ fontSize: 12, color: "var(--ink-muted)" }}>No history yet.</p>
            )}
            {(history?.audits ?? []).map(row => (
              <div key={row.audit_date} style={{ fontSize: 12, borderBottom: "1px solid var(--border)", paddingBottom: 6 }}>
                <span style={{ fontWeight: 600, color: "var(--ink)" }}>{row.audit_date}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

export function StrategyHealth() {
  const [tab, setTab] = useState<"daily" | "weekly">("daily");

  const tabBtn = (id: "daily" | "weekly", label: string) => (
    <button
      onClick={() => setTab(id)}
      className="btn"
      style={{
        background: tab === id ? "var(--accent-subtle)" : "transparent",
        color: tab === id ? "var(--accent)" : "var(--ink-muted)",
        border: "none", fontWeight: 600, fontSize: 13,
      }}
    >
      {label}
    </button>
  );

  return (
    <div className="p-4 md:p-6 flex flex-col gap-4">
      <div>
        <h1 className="text-lg font-semibold" style={{ color: "var(--ink)" }}>Strategy Health</h1>
        <div style={{ display: "flex", gap: 4, marginTop: 8 }}>
          {tabBtn("daily", "Daily Audit")}
          {tabBtn("weekly", "Weekly Review")}
        </div>
      </div>

      {tab === "daily" ? <DailyView /> : <WeeklyView />}
    </div>
  );
}
