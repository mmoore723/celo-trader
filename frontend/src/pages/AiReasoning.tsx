/**
 * AiReasoning.tsx — full prompt/response replay log for every AI call.
 *
 * Added 2026-07-20 per explicit user request: before trusting AI narration
 * or decision support (entry veto/resize), the user wants to see the EXACT
 * prompt sent and EXACT raw response received — not a summary — so
 * hallucination, prompt drift, or a silent model change can be caught by
 * inspection. Every call is logged regardless of success/failure, so this
 * is the complete trail (ai_reasoning_log), not a highlight reel.
 */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, AlertTriangle } from "lucide-react";
import { api, type AiReasoningEntry } from "../lib/api";
import { PageLoader } from "../components/PageLoader";

const EVENT_LABELS: Record<string, string> = {
  entry_narration:     "Entry narration (phase 1)",
  exit_narration:      "Exit narration (phase 1)",
  entry_veto:          "Entry decision support (phase 2)",
  daily_audit_summary:  "Daily strategy audit summary",
  weekly_audit_summary: "Weekly strategy review recommendation",
};

const EVENT_FILTERS = [
  "", "entry_narration", "exit_narration", "entry_veto",
  "daily_audit_summary", "weekly_audit_summary",
];

function ActionBadge({ entry }: { entry: AiReasoningEntry }) {
  if (entry.error) {
    return (
      <span style={{ display: "inline-flex", alignItems: "center", gap: 4, color: "#f0883e", fontSize: 12 }}>
        <AlertTriangle size={12} /> failed / fell back to approve
      </span>
    );
  }
  if (entry.event_type === "entry_veto") {
    return (
      <span style={{
        fontSize: 12, fontWeight: 600,
        color: entry.applied ? "var(--negative)" : "var(--positive)",
      }}>
        {entry.applied ? "vetoed / reduced size" : "approved"}
      </span>
    );
  }
  return null;
}

function Row({ entry }: { entry: AiReasoningEntry }) {
  const [open, setOpen] = useState(false);
  let snapshot: unknown = null;
  try { snapshot = JSON.parse(entry.feature_snapshot_json); } catch { /* best-effort */ }

  return (
    <div className="card" style={{ padding: 0, overflow: "hidden" }}>
      <button
        onClick={() => setOpen((o) => !o)}
        style={{
          width: "100%", display: "flex", alignItems: "center", gap: 10,
          padding: "10px 12px", background: "transparent", border: "none",
          cursor: "pointer", textAlign: "left",
        }}
      >
        {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        <span style={{ fontSize: 12, color: "var(--ink-faint)", width: 150, flexShrink: 0 }}>
          {entry.ts?.replace("T", " ").slice(0, 19)}
        </span>
        <span style={{ fontSize: 12, fontWeight: 600, width: 60, flexShrink: 0 }}>{entry.ticker}</span>
        <span style={{ fontSize: 12, color: "var(--ink-muted)", width: 220, flexShrink: 0 }}>
          {EVENT_LABELS[entry.event_type] ?? entry.event_type}
        </span>
        <span style={{ fontSize: 12, color: "var(--ink-faint)", width: 140, flexShrink: 0 }}>
          {entry.model ?? "—"}{entry.latency_ms ? ` · ${entry.latency_ms}ms` : ""}
        </span>
        <span style={{ flex: 1 }} />
        <ActionBadge entry={entry} />
      </button>

      {open && (
        <div style={{ padding: "0 12px 14px 34px", display: "flex", flexDirection: "column", gap: 10 }}>
          {entry.error && (
            <div style={{ fontSize: 12, color: "var(--negative)" }}>
              Error: {entry.error}
            </div>
          )}
          <div>
            <div style={{ fontSize: 11, fontWeight: 600, color: "var(--ink-faint)", marginBottom: 4 }}>
              EXACT PROMPT SENT (system + user, verbatim)
            </div>
            <pre style={{
              whiteSpace: "pre-wrap", fontSize: 12, background: "var(--bg-subtle)",
              padding: 10, borderRadius: 6, margin: 0, maxHeight: 280, overflowY: "auto",
            }}>
              {entry.prompt}
            </pre>
          </div>
          <div>
            <div style={{ fontSize: 11, fontWeight: 600, color: "var(--ink-faint)", marginBottom: 4 }}>
              RAW MODEL RESPONSE (verbatim, unedited)
            </div>
            <pre style={{
              whiteSpace: "pre-wrap", fontSize: 12, background: "var(--bg-subtle)",
              padding: 10, borderRadius: 6, margin: 0, maxHeight: 200, overflowY: "auto",
            }}>
              {entry.response_text ?? "(no response — see error above)"}
            </pre>
          </div>
          {snapshot != null && (
            <div>
              <div style={{ fontSize: 11, fontWeight: 600, color: "var(--ink-faint)", marginBottom: 4 }}>
                INPUT DATA SNAPSHOT (exact values fed into the prompt)
              </div>
              <pre style={{
                whiteSpace: "pre-wrap", fontSize: 11, color: "var(--ink-muted)",
                background: "var(--bg-subtle)", padding: 10, borderRadius: 6, margin: 0,
                maxHeight: 160, overflowY: "auto",
              }}>
                {JSON.stringify(snapshot, null, 2)}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export function AiReasoning() {
  const [eventType, setEventType] = useState("");
  const [ticker, setTicker] = useState("");
  const [onlyErrors, setOnlyErrors] = useState(false);

  const { data, isLoading } = useQuery({
    queryKey: ["ai-reasoning-log", eventType, ticker, onlyErrors],
    queryFn: () => api.aiReasoning.log({
      limit: 100,
      eventType: eventType || undefined,
      ticker: ticker || undefined,
      onlyErrors,
    }),
    refetchInterval: 30_000,
  });

  if (isLoading) return <PageLoader label="AI Reasoning Log" />;

  const entries = data?.entries ?? [];

  return (
    <div className="p-4 md:p-6 flex flex-col gap-4">
      <div>
        <h1 className="text-lg font-semibold" style={{ color: "var(--ink)" }}>AI Reasoning Log</h1>
        <p style={{ fontSize: 12, color: "var(--ink-muted)" }}>
          Every prompt sent to and response received from the AI reasoning layer — narration and
          decision support alike, successful or failed. This is the literal replay trail, not a
          summary: use it to check the AI isn't hallucinating, drifting from the intended prompt,
          or behaving differently after an Anthropic-side model update.
        </p>
      </div>

      <div className="card" style={{ padding: 12, display: "flex", gap: 12, flexWrap: "wrap", alignItems: "center" }}>
        <select className="select" value={eventType} onChange={(e) => setEventType(e.target.value)}>
          {EVENT_FILTERS.map((v) => (
            <option key={v} value={v}>{v ? (EVENT_LABELS[v] ?? v) : "All event types"}</option>
          ))}
        </select>
        <input
          className="input"
          placeholder="Filter by ticker (e.g. SPY)"
          value={ticker}
          onChange={(e) => setTicker(e.target.value.toUpperCase())}
          style={{ maxWidth: 180 }}
        />
        <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13, cursor: "pointer" }}>
          <input type="checkbox" checked={onlyErrors} onChange={(e) => setOnlyErrors(e.target.checked)} />
          Only failed / fell-back-to-approve calls
        </label>
        <span style={{ marginLeft: "auto", fontSize: 12, color: "var(--ink-faint)" }}>
          {entries.length} entr{entries.length === 1 ? "y" : "ies"} (most recent 100)
        </span>
      </div>

      {entries.length === 0 ? (
        <div className="card" style={{ padding: 20, textAlign: "center", color: "var(--ink-muted)" }}>
          No AI reasoning calls logged yet for this filter. If AI_REASONING_ENABLED and
          AI_DECISION_SUPPORT_ENABLED are on, entries will appear here as the bot trades.
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          {entries.map((e) => <Row key={e.id} entry={e} />)}
        </div>
      )}
    </div>
  );
}
