/**
 * Terms.tsx — Terms of Service gate + read-only view.
 *
 * Gate mode  (viewOnly=false): user must accept before accessing the dashboard.
 * Review mode (viewOnly=true):  already-accepted user reviewing the disclosure.
 *
 * All legal text lives in terms-content.ts — edit there to update the ToS.
 * To re-prompt all users after changes: bump CURRENT_TERMS_VERSION in auth/users.py.
 */
import { useState } from "react";
import { useAuth } from "../contexts/AuthContext";
import { SECTIONS, TERMS_VERSION, TERMS_DATE } from "./terms-content";

interface TermsProps {
  viewOnly?: boolean;
}

export function Terms({ viewOnly = false }: TermsProps) {
  const { acceptTerms, logout } = useAuth();
  const [busy, setBusy] = useState(false);

  async function handleAccept() {
    setBusy(true);
    try { await acceptTerms(); }
    finally { setBusy(false); }
  }

  return (
    <div style={s.backdrop}>
      <div style={s.card}>

        {/* ── Header ─────────────────────────────────────────────────────── */}
        <div style={s.header}>
          <span style={s.badge}>Legal Disclosure</span>
          <h1 style={s.title}>Celo Trader — Terms of Service</h1>
          <p style={s.subtitle}>
            {viewOnly
              ? `Version ${TERMS_VERSION} · ${TERMS_DATE}`
              : "Read carefully. You must agree to access the dashboard."}
          </p>
        </div>

        {/* ── Scrollable body ─────────────────────────────────────────────── */}
        <div style={s.scroll}>
          {SECTIONS.map((sec) =>
            sec.allCaps ? (
              /* CFTC / SEC required ALL-CAPS blocks */
              <div key={sec.id} style={s.capsBlock}>
                <p style={s.capsText}>{sec.body}</p>
              </div>
            ) : (
              <div key={sec.id} style={s.section}>
                {sec.heading && <h3 style={s.secTitle}>{sec.heading}</h3>}
                <p style={s.secBody}>{sec.body}</p>
              </div>
            )
          )}

          <p style={s.lastUpdated}>
            Version {TERMS_VERSION} · {TERMS_DATE}
          </p>
        </div>

        {/* ── Footer buttons ──────────────────────────────────────────────── */}
        <div style={s.footer}>
          {viewOnly ? (
            <button style={s.acceptBtn} onClick={() => window.history.back()}>
              ← Back to Dashboard
            </button>
          ) : (
            <>
              <button style={s.declineBtn} onClick={logout} disabled={busy}>
                Decline &amp; Sign Out
              </button>
              <button
                style={{ ...s.acceptBtn, opacity: busy ? 0.7 : 1 }}
                onClick={handleAccept}
                disabled={busy}
              >
                {busy ? "Saving…" : "I Have Read and Agree to These Terms"}
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Styles ────────────────────────────────────────────────────────────────────
const s: Record<string, React.CSSProperties> = {
  backdrop: {
    minHeight: "100vh", width: "100%", display: "flex",
    alignItems: "center", justifyContent: "center",
    background: "linear-gradient(135deg,#060c19 0%,#0d1a2e 50%,#060c19 100%)",
    fontFamily: "Inter,sans-serif", padding: "24px",
  },
  card: {
    width: "100%", maxWidth: 700,
    background: "rgba(13,24,46,0.97)",
    border: "1px solid rgba(0,200,83,0.2)",
    borderRadius: 20, overflow: "hidden",
    boxShadow: "0 0 60px rgba(0,200,83,0.08),0 20px 60px rgba(0,0,0,0.7)",
    display: "flex", flexDirection: "column", maxHeight: "92vh",
  },
  header: {
    padding: "28px 36px 18px",
    borderBottom: "1px solid rgba(255,255,255,0.06)",
    flexShrink: 0,
  },
  badge: {
    display: "inline-block", padding: "3px 10px",
    background: "rgba(0,200,83,0.12)", color: "#00c853",
    borderRadius: 20, fontSize: 11, fontWeight: 600,
    letterSpacing: "0.05em", textTransform: "uppercase", marginBottom: 10,
  },
  title: {
    margin: "0 0 6px", fontSize: 20, fontWeight: 700, color: "#fff",
  },
  subtitle: {
    margin: 0, fontSize: 12, color: "#64748b",
  },
  scroll: {
    flex: 1, overflowY: "auto", padding: "18px 36px",
  },
  section: {
    marginBottom: 18, paddingBottom: 18,
    borderBottom: "1px solid rgba(255,255,255,0.05)",
  },
  secTitle: {
    margin: "0 0 6px", fontSize: 12, fontWeight: 700,
    color: "#00c853", textTransform: "uppercase", letterSpacing: "0.04em",
  },
  secBody: {
    margin: 0, fontSize: 12, color: "#94a3b8", lineHeight: 1.75,
  },
  capsBlock: {
    margin: "0 0 18px",
    padding: "14px 16px",
    background: "rgba(220,38,38,0.07)",
    border: "1px solid rgba(220,38,38,0.2)",
    borderRadius: 8,
  },
  capsText: {
    margin: 0, fontSize: 11, color: "#fca5a5",
    lineHeight: 1.7, fontWeight: 600, letterSpacing: "0.01em",
  },
  lastUpdated: {
    fontSize: 10, color: "#334155", marginTop: 8,
    textAlign: "center", lineHeight: 1.6,
  },
  footer: {
    padding: "18px 36px",
    borderTop: "1px solid rgba(255,255,255,0.06)",
    display: "flex", gap: 12, justifyContent: "flex-end",
    flexShrink: 0,
  },
  declineBtn: {
    padding: "11px 18px", background: "transparent",
    border: "1px solid rgba(255,255,255,0.1)", borderRadius: 10,
    fontSize: 13, color: "#64748b", cursor: "pointer",
    fontFamily: "Inter,sans-serif",
  },
  acceptBtn: {
    padding: "11px 22px",
    background: "linear-gradient(135deg,#00c853,#00e676)",
    border: "none", borderRadius: 10, fontSize: 13, fontWeight: 600,
    color: "#060c19", cursor: "pointer", fontFamily: "Inter,sans-serif",
  },
};
