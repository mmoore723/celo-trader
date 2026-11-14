/**
 * Login.tsx — Landing page + login form for celotrader.com.
 *
 * Left panel (desktop): hero headline, 3 feature callouts, disclaimer.
 * Right panel: logo, login form, ToS link.
 * On mobile: stacked vertically (hero → form).
 */
import { useState, type FormEvent } from "react";
import { useAuth } from "../contexts/AuthContext";

// ── Feature cards ─────────────────────────────────────────────────────────────

const FEATURES = [
  {
    icon: "📡",
    title: "Pre-Market Intelligence",
    body:  "Review the tickers your enabled strategies can trade, with market context and recorded setup checks.",
  },
  {
    icon: "⚡",
    title: "Automated Execution",
    body:  "Follow automated entries and position management using your configured strategy rules and account limits.",
  },
  {
    icon: "📊",
    title: "Actionable Analytics",
    body:  "Review saved trades, results and decision records by strategy and ticker. Keep research comparisons separate from broker fills.",
  },
];

// ── Component ─────────────────────────────────────────────────────────────────

export function Login() {
  const { login }               = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [staySignedIn, setStay] = useState(true);
  const [showPw, setShowPw]     = useState(false);
  const [error, setError]       = useState<string | null>(null);
  const [loading, setLoading]   = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!username) { setError("Enter your username"); return; }
    if (!password) { setError("Enter your password"); return; }
    setError(null);
    setLoading(true);
    try {
      const r = await fetch("/api/auth/login", {
        method:      "POST",
        credentials: "include",
        headers:     { "Content-Type": "application/json" },
        body:        JSON.stringify({ username, password, stay_signed_in: staySignedIn }),
      });
      const data = await r.json();
      if (!r.ok) throw new Error(data.detail || "Login failed");
      login({ email: data.username || username, name: data.username || username,
              user_id: data.user_id, is_admin: !!data.is_admin, access_profile: data.access_profile ?? "legacy",
              terms_accepted: data.terms_accepted === true });
    } catch (e: any) {
      setError(e.message || "Login failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div style={s.backdrop}>
      {/* Responsive grid — stack on mobile */}
      <style>{`
        .celo-login-shell {
          display: grid;
          grid-template-columns: minmax(0,1fr) minmax(0,400px);
          gap: 48px;
          max-width: 960px;
          width: 100%;
          z-index: 1;
        }
        @media (max-width: 720px) {
          .celo-login-shell {
            grid-template-columns: 1fr;
            gap: 28px;
          }
          .celo-login-hero-extra { display: none; }
        }
      `}</style>

      {/* Mascot watermark */}
      <img src="/mascot.png" aria-hidden="true"
        style={{ position:"fixed", bottom:-80, right:-80, width:520, height:520,
                 objectFit:"contain", opacity:0.05, pointerEvents:"none",
                 userSelect:"none", zIndex:0 }} />

      <div className="celo-login-shell">

        {/* ── LEFT: Hero panel ── */}
        <div style={s.hero}>
          {/* Logo mark */}
          <div style={{ display:"flex", alignItems:"center", gap:12, marginBottom:36 }}>
            <img src="/logo.png" alt="" style={{ width:42, height:42, objectFit:"contain",
                filter:"drop-shadow(0 0 16px rgba(0,200,83,0.6))" }}
              onError={(e) => { (e.target as HTMLImageElement).src = "/favicon.svg"; }} />
            <span style={{ fontSize:20, fontWeight:700, color:"#fff", letterSpacing:"-0.5px" }}>
              Celo Trader
            </span>
          </div>

          {/* Headline */}
          <h1 style={s.headline}>
            Your trading workspace.{" "}
            <span style={{ color:"#00c853" }}>Built for Clarity</span>
          </h1>
          <p style={s.sub}>
            Bring strategy research, automated options trading and practical learning together.
            Sign in to review your settings, follow decisions and understand your results.
          </p>

          {/* Feature cards + disclaimer — hidden on very small screens */}
          <div className="celo-login-hero-extra"
               style={{ display:"flex", flexDirection:"column", gap:18, margin:"32px 0 36px" }}>
            {FEATURES.map((f) => (
              <div key={f.title} style={s.featureCard}>
                <span style={{ fontSize:24, lineHeight:1 }}>{f.icon}</span>
                <div>
                  <div style={{ fontSize:14, fontWeight:700, color:"#fff", marginBottom:4 }}>
                    {f.title}
                  </div>
                  <div style={{ fontSize:13, color:"#94a3b8", lineHeight:1.55 }}>{f.body}</div>
                </div>
              </div>
            ))}
          </div>

          {/* Disclaimer block */}
          <div className="celo-login-hero-extra" style={s.disclaimer}>
            <strong style={{ color:"#cbd5e1", fontSize:11 }}>
              For Educational &amp; Informational Use Only
            </strong>
            <p style={{ margin:"4px 0 0", fontSize:11, color:"#64748b", lineHeight:1.6 }}>
              Celo Trader is a software tool, not a registered investment adviser. Past
              performance does not guarantee future results. All trading involves substantial
              risk of loss. You are solely responsible for any trades placed in your own
              brokerage account. By accessing this platform you agree to our{" "}
              <a href="/#/terms" style={{ color:"#00c853", textDecoration:"underline" }}>
                Terms of Service
              </a>
              .
            </p>
          </div>
        </div>

        {/* ── RIGHT: Login card ── */}
        <div style={s.loginSide}>
          <div style={s.card}>
            {/* Logo (mobile also shows this) */}
            <div style={s.logoWrap}>
              <img src="/logo.png" alt="Celo Trader" style={s.logo}
                onError={(e) => { (e.target as HTMLImageElement).src = "/favicon.svg"; }} />
            </div>

            <h2 style={s.cardTitle}>Welcome Back</h2>
            <p style={s.cardSub}>Sign in to your trading dashboard</p>
            <a href="/#/about" style={{ color: "#94a3b8", marginBottom: 18 }}>About CELO Trader</a>

            {error && (
              <div style={s.errorBanner}>
                <span style={{ marginRight:6 }}>⚠️</span>{error}
              </div>
            )}

            <form onSubmit={handleSubmit} style={s.form}>
              <div style={s.inputWrap}>
                <input
                  type="text" value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  placeholder="Username"
                  autoFocus autoComplete="username"
                  style={s.input}
                />
              </div>
              <div style={s.inputWrap}>
                <input
                  type={showPw ? "text" : "password"} value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="Password"
                  autoComplete="current-password"
                  style={s.input}
                />
                <button type="button" onClick={() => setShowPw((p) => !p)}
                  style={s.eyeBtn} tabIndex={-1}>
                  {showPw ? "🙈" : "👁️"}
                </button>
              </div>

              {/* Stay signed in */}
              <label style={s.stayRow}>
                <div style={{ ...s.toggle, background: staySignedIn ? "#00c853" : "#334155" }}
                  onClick={() => setStay((p) => !p)}
                  role="checkbox" aria-checked={staySignedIn}>
                  <div style={{ ...s.toggleThumb,
                    transform: staySignedIn ? "translateX(18px)" : "translateX(2px)" }} />
                </div>
                <span style={s.stayLabel}>Stay signed in for 30 days</span>
              </label>

              <button type="submit" disabled={loading}
                style={{ ...s.submitBtn, opacity: loading ? 0.7 : 1 }}>
                {loading ? "Signing in…" : "Sign In"}
              </button>
            </form>

            {/* Footer links */}
            <div style={{ marginTop:20, display:"flex", flexDirection:"column",
                          alignItems:"center", gap:6 }}>
              <p style={s.footer}>Celo Trader © {new Date().getFullYear()}</p>
              <a href="/#/terms" style={{ fontSize:11, color:"#475569",
                textDecoration:"underline", cursor:"pointer" }}>
                Terms of Service &amp; Disclosures
              </a>
            </div>
          </div>
        </div>

      </div>
    </div>
  );
}

// ── Styles ────────────────────────────────────────────────────────────────────
const s: Record<string, React.CSSProperties> = {
  backdrop: {
    minHeight: "100vh", width: "100%",
    background: "linear-gradient(135deg, #060c19 0%, #0d1a2e 55%, #060c19 100%)",
    fontFamily: "Inter, sans-serif",
    display: "flex", alignItems: "center", justifyContent: "center",
    padding: "24px 16px",
    boxSizing: "border-box",
  },
  shell: {
    display: "grid",
    gridTemplateColumns: "minmax(0,1fr) minmax(0,400px)",
    gap: 48,
    maxWidth: 960,
    width: "100%",
    zIndex: 1,
    // Stack on narrow screens
    // (Tailwind not available here; use a <style> trick via a CSS variable or accept desktop-only grid)
  },
  hero: {
    display: "flex", flexDirection: "column",
    padding: "8px 0 8px",
  },
  headline: {
    margin: 0,
    fontSize: "clamp(22px, 3vw, 34px)",
    fontWeight: 800,
    color: "#fff",
    lineHeight: 1.25,
    letterSpacing: "-0.5px",
  },
  sub: {
    margin: "14px 0 0",
    fontSize: 15,
    color: "#94a3b8",
    lineHeight: 1.65,
  },
  featureCard: {
    display: "flex", gap: 14, alignItems: "flex-start",
    background: "rgba(255,255,255,0.035)",
    border: "1px solid rgba(255,255,255,0.07)",
    borderRadius: 12,
    padding: "14px 16px",
  },
  disclaimer: {
    background: "rgba(0,0,0,0.2)",
    border: "1px solid rgba(255,255,255,0.06)",
    borderRadius: 10,
    padding: "12px 14px",
  },
  loginSide: {
    display: "flex", alignItems: "center", justifyContent: "center",
  },
  card: {
    width: "100%",
    background: "rgba(13,24,46,0.92)",
    border: "1px solid rgba(0,200,83,0.2)",
    borderRadius: 20,
    padding: "36px 32px 28px",
    display: "flex", flexDirection: "column", alignItems: "center",
    boxShadow: "0 0 60px rgba(0,200,83,0.07), 0 20px 60px rgba(0,0,0,0.5)",
    backdropFilter: "blur(20px)",
  },
  logoWrap: {
    width: 72, height: 72, marginBottom: 16,
    display: "flex", alignItems: "center", justifyContent: "center",
  },
  logo: {
    width: "100%", height: "100%", objectFit: "contain",
    filter: "drop-shadow(0 0 16px rgba(0,200,83,0.5))",
  },
  cardTitle: {
    margin: 0, fontSize: 20, fontWeight: 700, color: "#fff", letterSpacing: "-0.3px",
  },
  cardSub: {
    margin: "6px 0 20px", fontSize: 13, color: "#64748b", textAlign: "center",
  },
  errorBanner: {
    width: "100%", background: "rgba(220,38,38,0.12)",
    border: "1px solid rgba(220,38,38,0.3)", borderRadius: 8,
    padding: "10px 14px", fontSize: 13, color: "#fca5a5",
    marginBottom: 14, display: "flex", alignItems: "center", boxSizing: "border-box",
  },
  form: { width: "100%", display: "flex", flexDirection: "column", gap: 13 },
  inputWrap: { position: "relative", width: "100%" },
  input: {
    width: "100%", padding: "12px 44px 12px 16px",
    background: "rgba(255,255,255,0.06)", border: "1px solid rgba(255,255,255,0.12)",
    borderRadius: 10, fontSize: 15, color: "#fff", outline: "none",
    boxSizing: "border-box", fontFamily: "Inter, sans-serif", transition: "border-color 0.15s",
  },
  eyeBtn: {
    position: "absolute", right: 12, top: "50%", transform: "translateY(-50%)",
    background: "none", border: "none", cursor: "pointer", fontSize: 16, lineHeight: 1, padding: 4,
  },
  stayRow:   { display: "flex", alignItems: "center", gap: 10, cursor: "pointer" },
  toggle: {
    width: 40, height: 22, borderRadius: 11, position: "relative",
    cursor: "pointer", transition: "background 0.2s", flexShrink: 0,
  },
  toggleThumb: {
    position: "absolute", top: 3, width: 16, height: 16,
    borderRadius: "50%", background: "#fff", transition: "transform 0.2s",
  },
  stayLabel: { fontSize: 13, color: "#94a3b8", userSelect: "none" },
  submitBtn: {
    width: "100%", padding: "12px",
    background: "linear-gradient(135deg, #00c853, #00e676)",
    border: "none", borderRadius: 10, fontSize: 15, fontWeight: 600,
    color: "#060c19", cursor: "pointer", transition: "opacity 0.15s",
    fontFamily: "Inter, sans-serif", marginTop: 2,
  },
  footer: { margin: 0, fontSize: 11, color: "#334155", textAlign: "center" },
};
