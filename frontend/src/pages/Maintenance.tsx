/**
 * Maintenance.tsx — Branded loading / maintenance screen.
 *
 * Shown in two scenarios:
 *  1. "connecting"  — initial page load, waiting for /api/auth/me to respond.
 *                     Shows pulsing logo + "Connecting to markets…"
 *  2. "maintenance" — bot/server is intentionally offline.
 *                     Shows logo + "Down for scheduled maintenance" + progress bar.
 *
 * Usage in App.tsx:
 *   <Maintenance mode="connecting" />
 *   <Maintenance mode="maintenance" message="Back online at 6:00 AM ET" />
 */
import { useEffect, useState } from "react";

interface MaintenanceProps {
  mode?:    "connecting" | "maintenance";
  message?: string;   // optional sub-message for maintenance mode
}

export function Maintenance({ mode = "connecting", message }: MaintenanceProps) {
  const [dots, setDots] = useState(".");
  const [barPct, setBarPct] = useState(12);

  // Animated dots for "Connecting…" label
  useEffect(() => {
    const t = setInterval(() => {
      setDots((d) => (d.length >= 3 ? "." : d + "."));
    }, 500);
    return () => clearInterval(t);
  }, []);

  // Slow progress bar animation (never reaches 100 — user doesn't know how long)
  useEffect(() => {
    if (mode !== "maintenance") return;
    const t = setInterval(() => {
      setBarPct((p) => (p >= 88 ? 88 : p + 1));
    }, 800);
    return () => clearInterval(t);
  }, [mode]);

  const isConnecting   = mode === "connecting";
  const isMaintenance  = mode === "maintenance";

  return (
    <div style={styles.backdrop}>
      <div style={styles.card}>

        {/* ── Logo ── */}
        <div
          style={{
            ...styles.logoWrap,
            animation: isConnecting ? "celoPulse 2s ease-in-out infinite" : "none",
          }}
        >
          {/* Mascot image (boy with chart) for maintenance, logo (C) for connecting */}
          <img
            src={isMaintenance ? "/mascot.png" : "/logo.png"}
            alt="Celo Trader"
            style={styles.logo}
            onError={(e) => {
              // Fallback if image not uploaded yet
              (e.target as HTMLImageElement).src = "/logo.png";
              (e.target as HTMLImageElement).onerror = () => {
                (e.target as HTMLImageElement).src = "/favicon.svg";
              };
            }}
          />
        </div>

        {/* ── Title ── */}
        <h1 style={styles.title}>Celo Trader</h1>

        {/* ── Status message ── */}
        {isConnecting && (
          <div style={styles.statusRow}>
            <span style={styles.spinnerDot} />
            <span style={styles.statusText}>Connecting to markets{dots}</span>
          </div>
        )}

        {isMaintenance && (
          <>
            <p style={styles.maintTitle}>Down for scheduled maintenance</p>
            {message && <p style={styles.maintMsg}>{message}</p>}

            {/* Progress bar */}
            <div style={styles.progressTrack}>
              <div
                style={{
                  ...styles.progressBar,
                  width: `${barPct}%`,
                }}
              />
            </div>
          </>
        )}

        {/* ── Footer ── */}
        <p style={styles.footer}>
          {isConnecting
            ? "Establishing secure connection…"
            : "We'll be back shortly. No trades are affected."}
        </p>
      </div>

      {/* Pulse keyframes */}
      <style>{`
        @keyframes celoPulse {
          0%, 100% { opacity: 1;   transform: scale(1);    filter: drop-shadow(0 0 24px rgba(0,200,83,0.5)); }
          50%       { opacity: 0.7; transform: scale(0.96); filter: drop-shadow(0 0 40px rgba(0,200,83,0.8)); }
        }
        @keyframes spin {
          from { transform: rotate(0deg); }
          to   { transform: rotate(360deg); }
        }
      `}</style>
    </div>
  );
}

// ── Styles ────────────────────────────────────────────────────────────────────
const styles: Record<string, React.CSSProperties> = {
  backdrop: {
    minHeight:      "100vh",
    width:          "100%",
    display:        "flex",
    alignItems:     "center",
    justifyContent: "center",
    background:     "linear-gradient(135deg, #060c19 0%, #0d1a2e 50%, #060c19 100%)",
    fontFamily:     "Inter, sans-serif",
  },
  card: {
    display:        "flex",
    flexDirection:  "column",
    alignItems:     "center",
    gap:            0,
    padding:        "60px 40px",
    maxWidth:       400,
    width:          "100%",
  },
  logoWrap: {
    width:          120,
    height:         120,
    marginBottom:   28,
  },
  logo: {
    width:          "100%",
    height:         "100%",
    objectFit:      "contain",
    filter:         "drop-shadow(0 0 24px rgba(0,200,83,0.45))",
  },
  title: {
    margin:         "0 0 20px",
    fontSize:       28,
    fontWeight:     700,
    color:          "#fff",
    letterSpacing:  "-0.5px",
  },
  statusRow: {
    display:        "flex",
    alignItems:     "center",
    gap:            10,
    marginBottom:   20,
  },
  spinnerDot: {
    width:          10,
    height:         10,
    borderRadius:   "50%",
    background:     "#00c853",
    boxShadow:      "0 0 8px #00c853",
    animation:      "celoPulse 1.2s ease-in-out infinite",
    flexShrink:     0,
  },
  statusText: {
    fontSize:       16,
    color:          "#94a3b8",
    fontVariantNumeric: "tabular-nums",
    minWidth:       200,
  },
  maintTitle: {
    margin:         "0 0 8px",
    fontSize:       18,
    fontWeight:     600,
    color:          "#e2e8f0",
    textAlign:      "center",
  },
  maintMsg: {
    margin:         "0 0 24px",
    fontSize:       13,
    color:          "#64748b",
    textAlign:      "center",
  },
  progressTrack: {
    width:          280,
    height:         4,
    background:     "rgba(255,255,255,0.08)",
    borderRadius:   2,
    overflow:       "hidden",
    marginBottom:   24,
  },
  progressBar: {
    height:         "100%",
    background:     "linear-gradient(90deg, #00c853, #00e676)",
    borderRadius:   2,
    transition:     "width 0.8s ease",
    boxShadow:      "0 0 8px rgba(0,200,83,0.6)",
  },
  footer: {
    margin:         "8px 0 0",
    fontSize:       12,
    color:          "#334155",
    textAlign:      "center",
  },
};
