import { strategyVariant, strategyVersion } from "../../lib/strategyIdentity.js";

export function StrategyIdentity({ id, version, tickers, label }: {
  id: string; version?: string; tickers: string[]; label: string;
}) {
  return <div className="mb-3 space-y-1.5">
    <p className="text-xs" style={{ color: "var(--ink-muted)" }}>
      {[strategyVariant(id), strategyVersion(version)].filter(Boolean).join(" · ")}
    </p>
    <div className="flex flex-wrap items-center gap-1.5 text-xs">
      <span style={{ color: "var(--ink-muted)" }}>{label}</span>
      {[...new Set(tickers)].sort().map(ticker => <span key={ticker}
        className="rounded px-2 py-0.5 font-semibold"
        style={{ background: "var(--surface)", border: "1px solid var(--border)", color: "var(--ink)" }}>{ticker}</span>)}
    </div>
  </div>;
}
