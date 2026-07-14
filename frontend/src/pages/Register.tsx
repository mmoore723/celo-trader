/**
 * Register.tsx — Self-registration via invite token.
 *
 * URL: /#/register?token=<uuid>
 * POSTs to POST /api/auth/register.
 * On success, redirects to login.
 */
import { useState, type FormEvent } from "react";
import { useSearchParams, useNavigate } from "react-router-dom";
import { PasswordChecklist, isPasswordValid } from "../components/PasswordChecklist";

export function Register() {
  const [params]            = useSearchParams();
  const navigate            = useNavigate();
  const token               = params.get("token") || "";
  const [username, setUser] = useState("");
  const [password, setPw]   = useState("");
  const [confirm, setConf]  = useState("");
  const [showPw, setShowPw] = useState(false);
  const [error, setError]   = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [done, setDone]     = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!token)    { setError("No invite token found in URL."); return; }
    if (!username) { setError("Choose a username."); return; }
    if (!password) { setError("Choose a password."); return; }
    if (!isPasswordValid(password)) { setError("Password does not meet complexity requirements."); return; }
    if (password !== confirm) { setError("Passwords do not match."); return; }
    setError(null);
    setLoading(true);
    try {
      const r = await fetch("/api/auth/register", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token, username, password }),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || "Registration failed");
      setDone(true);
      setTimeout(() => navigate("/"), 2000);
    } catch (e: any) {
      setError(e.message || "Registration failed");
    } finally {
      setLoading(false);
    }
  }

  if (done) return (
    <div style={styles.backdrop}>
      <div style={styles.card}>
        <h1 style={styles.title}>Account Created!</h1>
        <p style={{ color: "#94a3b8", fontSize: 14, marginTop: 8 }}>
          Redirecting to dashboard…
        </p>
      </div>
    </div>
  );

  return (
    <div style={styles.backdrop}>
      <div style={styles.card}>
        <h1 style={styles.title}>Create Your Account</h1>
        <p style={{ color: "#64748b", fontSize: 13, marginBottom: 24, textAlign: "center" }}>
          You've been invited to Celo Trader.
        </p>

        {error && (
          <div style={styles.errorBanner}>⚠️ {error}</div>
        )}

        {!token && (
          <p style={{ color: "#f87171", fontSize: 13, marginBottom: 16 }}>
            Invalid or missing invite link. Ask the admin to resend.
          </p>
        )}

        <form onSubmit={handleSubmit} style={styles.form}>
          <input
            className="input"
            type="text"
            placeholder="Choose a username"
            value={username}
            onChange={e => setUser(e.target.value)}
            autoFocus
            style={styles.input}
          />
          <div style={{ position: "relative" }}>
            <input
              className="input"
              type={showPw ? "text" : "password"}
              placeholder="Choose a password"
              value={password}
              onChange={e => setPw(e.target.value)}
              style={styles.input}
            />
            <button type="button" onClick={() => setShowPw(p => !p)}
              style={styles.eyeBtn}>{showPw ? "🙈" : "👁️"}</button>
          </div>

          {/* Live complexity checklist — appears on first keystroke */}
          <PasswordChecklist password={password} style={{ padding: "6px 4px" }} />

          <input
            className="input"
            type="password"
            placeholder="Confirm password"
            value={confirm}
            onChange={e => setConf(e.target.value)}
            style={styles.input}
          />
          <button type="submit" disabled={loading || !token}
            style={{ ...styles.submitBtn, opacity: (loading || !token) ? 0.6 : 1 }}>
            {loading ? "Creating account…" : "Create Account"}
          </button>
        </form>
      </div>
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  backdrop: {
    minHeight: "100vh", width: "100%", display: "flex",
    alignItems: "center", justifyContent: "center",
    background: "linear-gradient(135deg, #060c19 0%, #0d1a2e 50%, #060c19 100%)",
    fontFamily: "Inter, sans-serif", padding: 20,
  },
  card: {
    width: "100%", maxWidth: 380,
    background: "rgba(13,24,46,0.9)", border: "1px solid rgba(0,200,83,0.2)",
    borderRadius: 20, padding: "44px 36px 32px",
    display: "flex", flexDirection: "column", alignItems: "center",
    boxShadow: "0 0 60px rgba(0,200,83,0.08), 0 20px 60px rgba(0,0,0,0.5)",
  },
  title: { margin: 0, fontSize: 22, fontWeight: 700, color: "#fff" },
  errorBanner: {
    width: "100%", background: "rgba(220,38,38,0.12)", border: "1px solid rgba(220,38,38,0.3)",
    borderRadius: 8, padding: "10px 14px", fontSize: 13, color: "#fca5a5", marginBottom: 14,
  },
  form: { width: "100%", display: "flex", flexDirection: "column", gap: 12 },
  input: {
    width: "100%", padding: "13px 16px", background: "rgba(255,255,255,0.06)",
    border: "1px solid rgba(255,255,255,0.12)", borderRadius: 10,
    fontSize: 15, color: "#fff", outline: "none", boxSizing: "border-box",
    fontFamily: "Inter, sans-serif",
  },
  eyeBtn: {
    position: "absolute", right: 12, top: "50%", transform: "translateY(-50%)",
    background: "none", border: "none", cursor: "pointer", fontSize: 16,
  },
  submitBtn: {
    width: "100%", padding: 13, background: "linear-gradient(135deg, #00c853, #00e676)",
    border: "none", borderRadius: 10, fontSize: 15, fontWeight: 600,
    color: "#060c19", cursor: "pointer", fontFamily: "Inter, sans-serif", marginTop: 4,
  },
};
