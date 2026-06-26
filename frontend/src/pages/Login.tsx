/**
 * Login.tsx — Simple password login page for Celo Trader dashboard.
 *
 * Posts to POST /api/auth/login with { password, stay_signed_in }.
 * On success the backend sets a session cookie and AuthContext picks it up.
 */
import { useState, type FormEvent } from "react";
import { useAuth }             from "../contexts/AuthContext";

export function Login() {
  const { login }                   = useAuth();
  const [password, setPassword]     = useState("");
  const [staySignedIn, setStay]     = useState(true);
  const [showPw, setShowPw]         = useState(false);
  const [error, setError]           = useState<string | null>(null);
  const [loading, setLoading]       = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!password) { setError("Enter your password"); return; }
    setError(null);
    setLoading(true);

    try {
      const r = await fetch("/api/auth/login", {
        method:      "POST",
        credentials: "include",
        headers:     { "Content-Type": "application/json" },
        body:        JSON.stringify({ password, stay_signed_in: staySignedIn }),
      });
      const data = await r.json();
      if (!r.ok) throw new Error(data.detail || "Login failed");
      // Session cookie is now set — update auth context so App re-renders AppShell
      login({ email: "admin", name: "Trader" });
    } catch (e: any) {
      setError(e.message || "Login failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div style={styles.backdrop}>
      <div style={styles.card}>

        {/* Logo */}
        <div style={styles.logoWrap}>
          <img
            src="/logo.png"
            alt="Celo Trader"
            style={styles.logo}
            onError={(e) => {
              (e.target as HTMLImageElement).src = "/favicon.svg";
            }}
          />
        </div>

        <h1 style={styles.title}>Celo Trader</h1>
        <p style={styles.subtitle}>Enter your dashboard password to continue</p>

        {/* Error */}
        {error && (
          <div style={styles.errorBanner}>
            <span style={{ marginRight: 6 }}>⚠️</span>{error}
          </div>
        )}

        {/* Form */}
        <form onSubmit={handleSubmit} style={styles.form}>
          <div style={styles.inputWrap}>
            <input
              type={showPw ? "text" : "password"}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Password"
              autoFocus
              style={styles.input}
            />
            <button
              type="button"
              onClick={() => setShowPw((p) => !p)}
              style={styles.eyeBtn}
              tabIndex={-1}
            >
              {showPw ? "🙈" : "👁️"}
            </button>
          </div>

          {/* Stay signed in toggle */}
          <label style={styles.stayRow}>
            <div
              style={{
                ...styles.toggle,
                background: staySignedIn ? "#00c853" : "#334155",
              }}
              onClick={() => setStay((p) => !p)}
              role="checkbox"
              aria-checked={staySignedIn}
            >
              <div
                style={{
                  ...styles.toggleThumb,
                  transform: staySignedIn ? "translateX(18px)" : "translateX(2px)",
                }}
              />
            </div>
            <span style={styles.stayLabel}>Stay signed in for 30 days</span>
          </label>

          <button
            type="submit"
            disabled={loading}
            style={{ ...styles.submitBtn, opacity: loading ? 0.7 : 1 }}
          >
            {loading ? "Signing in…" : "Sign In"}
          </button>
        </form>

        <p style={styles.footer}>
          Celo Trader © {new Date().getFullYear()} · Algorithmic Options Trading
        </p>
      </div>
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
    padding:        "20px",
  },
  card: {
    width:          "100%",
    maxWidth:       380,
    background:     "rgba(13,24,46,0.9)",
    border:         "1px solid rgba(0,200,83,0.2)",
    borderRadius:   20,
    padding:        "44px 36px 32px",
    display:        "flex",
    flexDirection:  "column",
    alignItems:     "center",
    boxShadow:      "0 0 60px rgba(0,200,83,0.08), 0 20px 60px rgba(0,0,0,0.5)",
    backdropFilter: "blur(20px)",
  },
  logoWrap: {
    width:          88,
    height:         88,
    marginBottom:   20,
    display:        "flex",
    alignItems:     "center",
    justifyContent: "center",
  },
  logo: {
    width:          "100%",
    height:         "100%",
    objectFit:      "contain",
    filter:         "drop-shadow(0 0 20px rgba(0,200,83,0.5))",
  },
  title: {
    margin:         0,
    fontSize:       24,
    fontWeight:     700,
    color:          "#fff",
    letterSpacing:  "-0.5px",
  },
  subtitle: {
    margin:         "6px 0 24px",
    fontSize:       13,
    color:          "#64748b",
    textAlign:      "center",
  },
  errorBanner: {
    width:          "100%",
    background:     "rgba(220,38,38,0.12)",
    border:         "1px solid rgba(220,38,38,0.3)",
    borderRadius:   8,
    padding:        "10px 14px",
    fontSize:       13,
    color:          "#fca5a5",
    marginBottom:   14,
    display:        "flex",
    alignItems:     "center",
    boxSizing:      "border-box",
  },
  form: {
    width:          "100%",
    display:        "flex",
    flexDirection:  "column",
    gap:            14,
  },
  inputWrap: {
    position:       "relative",
    width:          "100%",
  },
  input: {
    width:          "100%",
    padding:        "13px 44px 13px 16px",
    background:     "rgba(255,255,255,0.06)",
    border:         "1px solid rgba(255,255,255,0.12)",
    borderRadius:   10,
    fontSize:       15,
    color:          "#fff",
    outline:        "none",
    boxSizing:      "border-box",
    fontFamily:     "Inter, sans-serif",
    transition:     "border-color 0.15s",
  },
  eyeBtn: {
    position:       "absolute",
    right:          12,
    top:            "50%",
    transform:      "translateY(-50%)",
    background:     "none",
    border:         "none",
    cursor:         "pointer",
    fontSize:       16,
    lineHeight:     1,
    padding:        4,
  },
  stayRow: {
    display:        "flex",
    alignItems:     "center",
    gap:            10,
    cursor:         "pointer",
  },
  toggle: {
    width:          40,
    height:         22,
    borderRadius:   11,
    position:       "relative",
    cursor:         "pointer",
    transition:     "background 0.2s",
    flexShrink:     0,
  },
  toggleThumb: {
    position:       "absolute",
    top:            3,
    width:          16,
    height:         16,
    borderRadius:   "50%",
    background:     "#fff",
    transition:     "transform 0.2s",
  },
  stayLabel: {
    fontSize:       13,
    color:          "#94a3b8",
    userSelect:     "none",
  },
  submitBtn: {
    width:          "100%",
    padding:        "13px",
    background:     "linear-gradient(135deg, #00c853, #00e676)",
    border:         "none",
    borderRadius:   10,
    fontSize:       15,
    fontWeight:     600,
    color:          "#060c19",
    cursor:         "pointer",
    transition:     "opacity 0.15s",
    fontFamily:     "Inter, sans-serif",
    marginTop:      4,
  },
  footer: {
    marginTop:      28,
    fontSize:       11,
    color:          "#334155",
    textAlign:      "center",
  },
};
