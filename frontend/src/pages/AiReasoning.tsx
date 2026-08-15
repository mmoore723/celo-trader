import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Bot, CheckCircle2, ChevronDown, ChevronRight,
  Eye, Filter, ShieldCheck, Sparkles, XCircle,
} from "lucide-react";
import { api, type AiReasoningEntry } from "../lib/api";
import { PageLoader } from "../components/PageLoader";

const EVENT_LABELS: Record<string, string> = {
  entry_narration: "Entry explanation",
  exit_narration: "Exit explanation",
  entry_veto: "Entry decision review",
  daily_audit_summary: "Daily strategy review",
  weekly_audit_summary: "Weekly strategy review",
};

const EVENT_FILTERS = [
  "", "entry_narration", "exit_narration", "entry_veto",
  "daily_audit_summary", "weekly_audit_summary",
];

function parseSnapshot(entry: AiReasoningEntry): Record<string, unknown> {
  try {
    const parsed = JSON.parse(entry.feature_snapshot_json || "{}");
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
}

function readableValue(value: unknown): string {
  if (typeof value === "number") return Number.isInteger(value) ? String(value) : value.toFixed(2);
  if (typeof value === "boolean") return value ? "Yes" : "No";
  return String(value ?? "—");
}

function decisionLabel(entry: AiReasoningEntry) {
  if (entry.error) return { label: "AI unavailable — bot fallback used", tone: "var(--negative)", icon: XCircle };
  if (entry.event_type !== "entry_veto") return { label: "Explanation only", tone: "#2563eb", icon: Eye };
  if (entry.applied) return { label: "AI changed the decision", tone: "var(--negative)", icon: ShieldCheck };
  return { label: "Passive review — no trade control", tone: "var(--positive)", icon: CheckCircle2 };
}

function ReasoningRow({ entry }: { entry: AiReasoningEntry }) {
  const [open, setOpen] = useState(false);
  const [technicalOpen, setTechnicalOpen] = useState(false);
  const snapshot = parseSnapshot(entry);
  const decision = decisionLabel(entry);
  const DecisionIcon = decision.icon;
  const strategy = snapshot.strategy_id ?? snapshot.strategy ?? snapshot.setup ?? "—";
  const direction = snapshot.direction ?? snapshot.side ?? "—";
  const confidence = snapshot.confidence ?? snapshot.score;
  const keyFacts = ([
    ["Strategy", strategy],
    ["Direction", direction],
    ["Confidence", typeof confidence === "number" ? `${(confidence <= 1 ? confidence * 100 : confidence).toFixed(0)}%` : confidence],
    ["Trade", entry.trade_id ? `#${entry.trade_id}` : "No trade linked"],
  ] as Array<[string, unknown]>).filter(([, value]) => value != null && value !== "—");

  return (
    <article className="card" style={{ padding: 0, overflow: "hidden" }}>
      <button
        onClick={() => setOpen((value) => !value)}
        style={{
          width: "100%", display: "grid", gridTemplateColumns: "24px 145px 72px minmax(170px, 1fr) minmax(210px, 1.2fr)",
          alignItems: "center", gap: 10, padding: "13px 14px", background: "transparent",
          border: 0, cursor: "pointer", textAlign: "left",
        }}
      >
        {open ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
        <span style={{ fontSize: 12, color: "var(--ink-faint)" }}>{entry.ts?.replace("T", " ").slice(0, 19)}</span>
        <strong style={{ fontSize: 13 }}>{entry.ticker || "—"}</strong>
        <span style={{ fontSize: 12, color: "var(--ink-muted)" }}>{EVENT_LABELS[entry.event_type] ?? entry.event_type}</span>
        <span style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 12, fontWeight: 600, color: decision.tone }}>
          <DecisionIcon size={14} /> {decision.label}
        </span>
      </button>

      {open && (
        <div style={{ borderTop: "1px solid var(--border)", padding: 14, display: "grid", gap: 14 }}>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(145px, 1fr))", gap: 8 }}>
            {keyFacts.map(([label, value]) => (
              <div key={String(label)} style={{ background: "var(--bg-subtle)", borderRadius: 8, padding: "9px 10px" }}>
                <div style={{ fontSize: 10, letterSpacing: ".07em", color: "var(--ink-faint)", textTransform: "uppercase" }}>{label}</div>
                <div style={{ marginTop: 3, fontSize: 13, fontWeight: 600 }}>{readableValue(value)}</div>
              </div>
            ))}
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) minmax(0, 1fr)", gap: 12 }}>
            <section style={{ padding: 12, borderRadius: 8, border: "1px solid var(--border)" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 11, fontWeight: 700, color: "var(--ink-faint)", marginBottom: 7 }}>
                <Bot size={13} /> WHAT THE AI SAID
              </div>
              <div style={{ whiteSpace: "pre-wrap", fontSize: 12, lineHeight: 1.55 }}>
                {entry.response_text || (entry.error ? "No response was returned." : "No explanation was recorded.")}
              </div>
            </section>
            <section style={{ padding: 12, borderRadius: 8, border: `1px solid ${entry.error ? "var(--negative)" : "var(--border)"}` }}>
              <div style={{ fontSize: 11, fontWeight: 700, color: "var(--ink-faint)", marginBottom: 7 }}>WHAT ACTUALLY HAPPENED</div>
              <div style={{ fontSize: 12, lineHeight: 1.55, color: decision.tone, fontWeight: 600 }}>{decision.label}</div>
              <div style={{ fontSize: 12, color: "var(--ink-muted)", marginTop: 5 }}>
                {entry.error
                  ? entry.error
                  : entry.applied
                    ? "The AI output was enforced. Review this carefully against later trade results."
                    : "The deterministic strategy and risk rules remained in control."}
              </div>
            </section>
          </div>

          <button className="btn btn-ghost" onClick={() => setTechnicalOpen((value) => !value)} style={{ justifySelf: "start" }}>
            {technicalOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />} Technical audit details
          </button>
          {technicalOpen && (
            <div style={{ display: "grid", gap: 10 }}>
              <details>
                <summary style={{ cursor: "pointer", fontSize: 12, fontWeight: 600 }}>Exact prompt sent</summary>
                <pre style={{ whiteSpace: "pre-wrap", fontSize: 11, background: "var(--bg-subtle)", padding: 10, borderRadius: 6, maxHeight: 260, overflow: "auto" }}>{entry.prompt}</pre>
              </details>
              <details>
                <summary style={{ cursor: "pointer", fontSize: 12, fontWeight: 600 }}>Exact feature snapshot</summary>
                <pre style={{ whiteSpace: "pre-wrap", fontSize: 11, background: "var(--bg-subtle)", padding: 10, borderRadius: 6, maxHeight: 220, overflow: "auto" }}>{JSON.stringify(snapshot, null, 2)}</pre>
              </details>
              <div style={{ fontSize: 11, color: "var(--ink-faint)" }}>Model: {entry.model ?? "—"} · Latency: {entry.latency_ms ? `${entry.latency_ms}ms` : "—"}</div>
            </div>
          )}
        </div>
      )}
    </article>
  );
}

export function AiReasoning() {
  const [eventType, setEventType] = useState("");
  const [ticker, setTicker] = useState("");
  const [onlyErrors, setOnlyErrors] = useState(false);
  const { data, isLoading } = useQuery({
    queryKey: ["ai-reasoning-log", eventType, ticker, onlyErrors],
    queryFn: () => api.aiReasoning.log({ limit: 100, eventType: eventType || undefined, ticker: ticker || undefined, onlyErrors }),
    refetchInterval: 30_000,
  });
  const entries = useMemo(() => data?.entries ?? [], [data?.entries]);
  const stats = useMemo(() => ({
    total: entries.length,
    passive: entries.filter((entry) => !entry.applied && !entry.error).length,
    applied: entries.filter((entry) => Boolean(entry.applied)).length,
    errors: entries.filter((entry) => Boolean(entry.error)).length,
  }), [entries]);

  if (isLoading) return <PageLoader label="AI Decision Audit" />;

  return (
    <div className="p-4 md:p-6 flex flex-col gap-4">
      <header>
        <div style={{ display: "flex", alignItems: "center", gap: 7, color: "#2563eb", fontSize: 11, fontWeight: 700, letterSpacing: ".11em" }}><Sparkles size={14} /> AI DECISION AUDIT</div>
        <h1 className="text-lg font-semibold" style={{ color: "var(--ink)", marginTop: 4 }}>What the AI considered—and what the bot actually did</h1>
        <p style={{ fontSize: 12, color: "var(--ink-muted)", maxWidth: 820 }}>
          Use this page to verify the AI, not to guess at its role. Passive reviews cannot block a trade. Applied decisions and failures are clearly identified and retain their exact technical audit trail.
        </p>
      </header>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, minmax(0, 1fr))", gap: 10 }}>
        {[["Calls reviewed", stats.total, "var(--ink)"], ["Passive / advisory", stats.passive, "#2563eb"], ["Applied to trading", stats.applied, "var(--positive)"], ["Failures / fallback", stats.errors, "var(--negative)"]].map(([label, value, color]) => (
          <div className="card" key={String(label)} style={{ padding: 13 }}><div style={{ fontSize: 11, color: "var(--ink-faint)" }}>{label}</div><div style={{ fontSize: 22, fontWeight: 700, color: String(color), marginTop: 3 }}>{value}</div></div>
        ))}
      </div>

      <div className="card" style={{ padding: 12, display: "flex", gap: 12, flexWrap: "wrap", alignItems: "center" }}>
        <Filter size={15} color="var(--ink-faint)" />
        <select className="select" value={eventType} onChange={(event) => setEventType(event.target.value)}>
          {EVENT_FILTERS.map((value) => <option key={value} value={value}>{value ? (EVENT_LABELS[value] ?? value) : "All AI events"}</option>)}
        </select>
        <input className="input" placeholder="Ticker (for example SPY)" value={ticker} onChange={(event) => setTicker(event.target.value.toUpperCase())} style={{ maxWidth: 190 }} />
        <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, cursor: "pointer" }}><input type="checkbox" checked={onlyErrors} onChange={(event) => setOnlyErrors(event.target.checked)} /> Only failures</label>
        <span style={{ marginLeft: "auto", fontSize: 11, color: "var(--ink-faint)" }}>Most recent 100 calls · refreshes every 30 seconds</span>
      </div>

      {entries.length === 0 ? (
        <div className="card" style={{ padding: 26, textAlign: "center", color: "var(--ink-muted)" }}>
          No AI calls match these filters. This does not mean the scanner stopped; deterministic strategy decisions are recorded in Scanner Opportunities.
        </div>
      ) : <div style={{ display: "flex", flexDirection: "column", gap: 7 }}>{entries.map((entry) => <ReasoningRow key={entry.id} entry={entry} />)}</div>}
    </div>
  );
}
