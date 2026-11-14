/**
 * Login.tsx — Landing page + login form for celotrader.com.
 *
 * Left panel (desktop): hero headline, 3 feature callouts, disclaimer.
 * Right panel: logo, login form, ToS link.
 * On mobile: stacked vertically (hero → form).
 */
import { useState, type FormEvent } from "react";
import "./login.css";
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
    <main className="celo-brand celo-login">
      <header className="login-nav"><a href="/#/about" className="login-brand"><span>C</span> CELO <b>TRADER</b></a><a href="/#/about">Back to home</a></header>
      <div className="login-layout">
        <section className="login-intro">
          <p className="login-eyebrow">YOUR NEXT CHAPTER</p>
          <h1>A clearer way to<br/><em>learn and trade.</em></h1>
          <p>Welcome back to CELO Trader. Pick up your lessons, explore the charts and follow your trading workspace.</p>
          <div className="login-features">{FEATURES.map(f=><article key={f.title}><span aria-hidden="true">{f.icon}</span><div><h2>{f.title}</h2><p>{f.body}</p></div></article>)}</div>
        </section>
        <section className="login-card" aria-labelledby="login-title">
          <p className="login-eyebrow">WELCOME BACK</p><h2 id="login-title">Make yourself at home.</h2><p>Sign in to your CELO account.</p>
          {error&&<p className="login-error" role="alert">{error}</p>}
          <form onSubmit={handleSubmit}>
            <label htmlFor="login-username">Username</label><input id="login-username" value={username} onChange={e=>setUsername(e.target.value)} autoComplete="username" required/>
            <label htmlFor="login-password">Password</label><div className="login-password"><input id="login-password" type={showPw?'text':'password'} value={password} onChange={e=>setPassword(e.target.value)} autoComplete="current-password" required/><button type="button" aria-label={showPw?'Hide password':'Show password'} aria-pressed={showPw} onClick={()=>setShowPw(!showPw)}>{showPw?'Hide':'Show'}</button></div>
            <label className="login-remember"><input type="checkbox" checked={staySignedIn} onChange={e=>setStay(e.target.checked)}/>Stay signed in for 30 days</label>
            <button className="login-submit" type="submit" disabled={loading}>{loading?'Signing in...':'Sign in'}</button>
          </form>
          <p className="login-join">New to CELO? <a href="/#/about">Explore plans and join the waitlist</a></p>
        </section>
      </div>
      <footer className="login-footer"><p>Options trading involves risk, including losing the money you invest. CELO Trader is software, not an investment adviser.</p><a href="/#/terms">Terms of Service &amp; Disclosures</a><span>CELO Trader © {new Date().getFullYear()}</span></footer>
    </main>
  );
}
