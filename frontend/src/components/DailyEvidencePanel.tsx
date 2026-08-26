import type { DailyEvidenceScorecard } from "../lib/api";

function valueOrDash(value: number | string | null, suffix = "") {
  return value === null ? "—" : `${value}${suffix}`;
}

export function DailyEvidencePanel({ data }: { data?: DailyEvidenceScorecard }) {
  if (!data?.account_scoped) {
    return (
      <div className="card p-4 text-xs" style={{ color: "var(--ink-muted)" }}>
        Connect the active brokerage account to build an account-isolated daily review.
      </div>
    );
  }
  const pf = data.trading.profit_factor === "infinite"
    ? "No losses"
    : valueOrDash(data.trading.profit_factor);
  const replayColor = data.replay.coverage_pct === 100 ? "var(--positive)" : "#ffd740";
  const stats = [
    { label: "Profit factor", value: pf, note: "gross wins ÷ gross losses" },
    { label: "Signal accuracy", value: valueOrDash(data.decisions.directional_accuracy_pct, "%"), note: `${data.decisions.measured} measured candidates` },
    { label: "Entry fills", value: valueOrDash(data.execution.entry_fill_rate_pct, "%"), note: `${data.execution.entry_filled}/${data.execution.entry_attempts} attempts` },
    { label: "Replay coverage", value: `${data.replay.coverage_pct}%`, note: data.replay.passed ? "evidence linked" : "links need review", color: replayColor },
  ];
  const missed = data.decisions.missed_executable_moves["60m"];
  return (
    <div className="card p-4 flex flex-col gap-3">
      <div>
        <h3 className="text-sm font-semibold" style={{ color: "var(--ink)" }}>What the evidence says</h3>
        <p className="text-xs mt-0.5" style={{ color: "var(--ink-muted)" }}>
          Profit, decision quality, order execution, and record completeness are scored separately.
        </p>
      </div>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
        {stats.map(stat => (
          <div key={stat.label} className="rounded-md px-3 py-2" style={{ background: "var(--muted)" }}>
            <p className="text-[10px] uppercase tracking-wide" style={{ color: "var(--ink-faint)" }}>{stat.label}</p>
            <p className="num text-base font-bold" style={{ color: stat.color ?? "var(--ink)" }}>{stat.value}</p>
            <p className="text-[10px]" style={{ color: "var(--ink-muted)" }}>{stat.note}</p>
          </div>
        ))}
      </div>
      {missed?.measured > 0 && (
        <p className="text-xs" style={{ color: "var(--ink-muted)" }}>
          Unentered setups with exact option quotes at 60 minutes: <strong>{missed.profitable}/{missed.measured}</strong> profitable
          {missed.avg_executable_return_pct !== null ? `, averaging ${missed.avg_executable_return_pct}% after buying at ask and marking at bid.` : "."}
        </p>
      )}
      <ul className="text-xs pl-4 list-disc" style={{ color: "var(--ink-muted)" }}>
        {data.observations.map((text, index) => <li key={`${index}-${text}`}>{text}</li>)}
      </ul>
      <p className="text-[10px]" style={{ color: "var(--ink-faint)" }}>{data.launch_readiness.note}</p>
    </div>
  );
}
