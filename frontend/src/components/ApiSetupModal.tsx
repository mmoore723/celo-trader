/**
 * ApiSetupModal.tsx — First-time broker API key onboarding popup.
 *
 * Shown automatically after login when no credentials are saved.
 * 3 steps: Alpaca keys → Tradier key → Done.
 * User can skip any step and come back via Settings → API Credentials.
 */
import { useState } from "react";
import { Eye, EyeOff, X, CheckCircle2, ChevronRight } from "lucide-react";

interface Props {
  onClose: () => void;
}

interface Creds {
  alpaca_key:    string;
  alpaca_secret: string;
  tradier_token: string;
}

function Field({
  label, value, onChange, placeholder, secret = false,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder: string;
  secret?: boolean;
}) {
  const [show, setShow] = useState(false);
  return (
    <div className="flex flex-col gap-1">
      <label className="text-xs font-medium" style={{ color: "var(--ink-muted)" }}>{label}</label>
      <div className="relative">
        <input
          type={secret && !show ? "password" : "text"}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          className="input w-full"
          style={{ paddingRight: secret ? "36px" : undefined }}
        />
        {secret && (
          <button
            type="button"
            onClick={() => setShow((s) => !s)}
            className="absolute right-2 top-1/2 -translate-y-1/2 p-1"
            style={{ color: "var(--ink-faint)" }}
            aria-label={show ? "Hide" : "Show"}
          >
            {show ? <EyeOff size={14} /> : <Eye size={14} />}
          </button>
        )}
      </div>
    </div>
  );
}

const STEPS = ["Alpaca", "Tradier", "Done"] as const;

export function ApiSetupModal({ onClose }: Props) {
  const [step, setStep]   = useState(0);
  const [saving, setSaving] = useState(false);
  const [creds, setCreds] = useState<Creds>({
    alpaca_key: "", alpaca_secret: "", tradier_token: "",
  });

  function set<K extends keyof Creds>(k: K, v: string) {
    setCreds((c) => ({ ...c, [k]: v }));
  }

  async function saveAndNext() {
    setSaving(true);
    try {
      await fetch("/api/settings/credentials", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(creds),
      });
    } catch { /* non-fatal — user can retry in Settings */ }
    setSaving(false);
    setStep((s) => s + 1);
  }

  return (
    <div
      style={{
        position: "fixed", inset: 0, zIndex: 1000,
        background: "rgba(0,0,0,0.35)",
        backdropFilter: "blur(2px)",
        display: "flex", alignItems: "center", justifyContent: "center",
        padding: "1rem",
      }}
    >
      <div
        className="card"
        style={{
          width: "100%", maxWidth: "460px",
          background: "var(--surface-bg)",
          border: "1px solid var(--border)",
          borderRadius: "12px",
          overflow: "hidden",
        }}
      >
        {/* Header */}
        <div style={{ padding: "1.25rem 1.25rem 0", display: "flex", alignItems: "flex-start", justifyContent: "space-between" }}>
          <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
            <div style={{
              width: 36, height: 36, borderRadius: 8,
              background: "var(--accent-subtle)",
              display: "flex", alignItems: "center", justifyContent: "center",
            }}>
              <span style={{ fontSize: 18 }}>🔑</span>
            </div>
            <div>
              <p style={{ fontSize: 15, fontWeight: 500, color: "var(--ink)", margin: 0 }}>Connect your broker</p>
              <p style={{ fontSize: 12, color: "var(--ink-muted)", margin: 0 }}>Required to place trades</p>
            </div>
          </div>
          <button onClick={onClose} style={{ color: "var(--ink-faint)", padding: 4 }} aria-label="Close">
            <X size={16} />
          </button>
        </div>

        {/* Step progress */}
        <div style={{ padding: "1rem 1.25rem 0" }}>
          <div style={{ display: "flex", gap: 6, marginBottom: 4 }}>
            {STEPS.map((_, i) => (
              <div key={i} style={{
                flex: 1, height: 3, borderRadius: 2,
                background: i <= step ? "var(--accent)" : "var(--border)",
                transition: "background 0.2s",
              }} />
            ))}
          </div>
          <p style={{ fontSize: 11, color: "var(--ink-faint)", margin: 0 }}>
            Step {step + 1} of {STEPS.length} — {STEPS[step]}
          </p>
        </div>

        {/* Step body */}
        <div style={{ padding: "1.25rem" }}>

          {step === 0 && (
            <div style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
              <div style={{
                background: "var(--accent-subtle)",
                border: "1px solid var(--accent-border)",
                borderRadius: 8,
                padding: "10px 12px",
                display: "flex", gap: 8, alignItems: "flex-start",
              }}>
                <span style={{ fontSize: 13, color: "var(--accent)", lineHeight: 1.5 }}>
                  ℹ️ Alpaca uses the same key pair for paper and live trading. Switch modes in Settings.
                </span>
              </div>
              <Field
                label="API key ID"
                value={creds.alpaca_key}
                onChange={(v) => set("alpaca_key", v)}
                placeholder="PKXXXXXXXXXXXXXXXXXXXXXXXX"
              />
              <Field
                label="Secret key"
                value={creds.alpaca_secret}
                onChange={(v) => set("alpaca_secret", v)}
                placeholder="••••••••••••••••••••••••••••••••"
                secret
              />
              <p style={{ fontSize: 11, color: "var(--ink-faint)", margin: 0 }}>
                Find your keys at <strong>alpaca.markets → API Keys</strong>. Stored encrypted on your account.
              </p>
            </div>
          )}

          {step === 1 && (
            <div style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
              <p style={{ fontSize: 13, color: "var(--ink-muted)", margin: 0 }}>
                Tradier is used for real-time options quotes and chains. You can add this later if you don't have a Tradier account.
              </p>
              <Field
                label="Tradier access token"
                value={creds.tradier_token}
                onChange={(v) => set("tradier_token", v)}
                placeholder="Bearer XXXXXXXXXXXXXXXXXXXXXXXX"
                secret
              />
              <p style={{ fontSize: 11, color: "var(--ink-faint)", margin: 0 }}>
                Find your token at <strong>tradier.com → API Access</strong>.
              </p>
            </div>
          )}

          {step === 2 && (
            <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: "0.75rem", padding: "0.5rem 0 0.25rem" }}>
              <CheckCircle2 size={40} style={{ color: "var(--accent)" }} />
              <p style={{ fontSize: 15, fontWeight: 500, color: "var(--ink)", margin: 0 }}>You're all set</p>
              <p style={{ fontSize: 13, color: "var(--ink-muted)", margin: 0, textAlign: "center" }}>
                Your credentials are saved. You can update them any time in Settings → API Credentials.
              </p>
            </div>
          )}
        </div>

        {/* Footer */}
        <div style={{
          padding: "0 1.25rem 1.25rem",
          display: "flex", gap: 8, justifyContent: "flex-end",
        }}>
          {step < 2 && (
            <button
              className="btn btn-ghost"
              style={{ fontSize: 13, color: "var(--ink-muted)" }}
              onClick={() => setStep((s) => s + 1)}
            >
              Skip
            </button>
          )}
          {step < 2 ? (
            <button
              className="btn btn-primary"
              style={{ fontSize: 13 }}
              onClick={saveAndNext}
              disabled={saving}
            >
              Save & continue <ChevronRight size={13} />
            </button>
          ) : (
            <button className="btn btn-primary" style={{ fontSize: 13 }} onClick={onClose}>
              Start trading
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
