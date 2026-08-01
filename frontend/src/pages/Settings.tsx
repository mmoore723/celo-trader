/**
 * Settings.tsx — Bot configuration form + API credentials.
 */
import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Save, Eye, EyeOff, Key } from "lucide-react";
import { api, type AppSettings } from "../lib/api";

function Toggle({ checked, onChange, label }: { checked: boolean; onChange: (v: boolean) => void; label: string }) {
  return (
    <label className="flex items-center justify-between gap-3 cursor-pointer py-2">
      <span className="text-sm" style={{ color: "var(--ink)" }}>{label}</span>
      <div
        className={`toggle-track ${checked ? "on" : ""}`}
        onClick={() => onChange(!checked)}
      >
        <div className="toggle-thumb" />
      </div>
    </label>
  );
}

const DEFAULT: AppSettings = {
  paper_trading: true,
  risk_pct: 5.0,
  risk_auto: true,
  growth_mode: false,
  flip_trading_enabled: true,
  max_concurrent_positions: 2,
  rr_ratio_mode: "auto",
  watchlist: ["SPY"],
  orb_enabled: true,
  vwap_pullback_enabled: true,
  fvg_enabled: true,
  ifvg_enabled: true,
  bos_mss_enabled: true,   // kept for API compatibility; strategy is disabled in router
  chan_break_enabled: true,
  mid_brk_enabled: false,  // disabled 2026-07-23 — 13 backtested configs, all negative, see audit
  trend_cont_enabled: true,
  aft_rev_enabled: true,   // Afternoon Reversal — added to Settings 2026-07-20
  gap_go_enabled: true,    // Gap and Go — added 2026-07-23, flipped ON 2026-07-31
  liquidity_sweep_enabled: true,  // Liquidity Sweep Reversal — added 2026-07-31, ON by default
  signal_only_mode: false,  // true = bot alerts only, no order placement
  display_timezone: "America/New_York",
  // Trade parameters
  orb_stage1_gain_pct: 50,
  orb_stop_loss_pct: 20,
  spread_gate_pct: 8,   // was stale 25, fixed 2026-07-22
  vol_roc_threshold: 0.50,
  daily_loss_hard_cap_pct: 10,  // added 2026-07-24 — was hardcoded, non-adjustable
  min_grade_filter_enabled: false,  // added 2026-07-24 — off by default
  min_entry_grade: "C",
  max_position_dollars_pct: 15,  // added 2026-07-24 — was hardcoded, no UI
  simplified_exit_mode: true,        // added 2026-07-22 — 3-rule exit, on by default (see research note in-form)
  mtf_confirmation_enabled: false,   // added 2026-07-23 — live 1Hour bias gate, off by default (can't backtest)
  inst_orb_immediate_entry_enabled: false,  // added 2026-07-31 — skip the retest wait, off by default (not backtested)
};

const TIMEZONES = [
  { value: "America/New_York",    label: "Eastern (ET) — NYSE hours" },
  { value: "America/Chicago",     label: "Central (CT)" },
  { value: "America/Denver",      label: "Mountain (MT)" },
  { value: "America/Los_Angeles", label: "Pacific (PT)" },
  { value: "America/Phoenix",     label: "Arizona (MST, no DST)" },
  { value: "UTC",                 label: "UTC" },
];

// ── Credentials panel ──────────────────────────────────────────────────────
function CredentialField({
  label, name, value, onChange, show, onToggle, hint
}: {
  label: string; name: string; value: string;
  onChange: (v: string) => void; show: boolean;
  onToggle: () => void; hint?: string;
}) {
  return (
    <div className="flex flex-col gap-1">
      <label className="text-xs font-medium" style={{ color: "var(--ink-muted)" }}>{label}</label>
      <div className="relative">
        <input
          type={show ? "text" : "password"}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={hint || "Enter key…"}
          className="input w-full pr-10 font-mono text-sm"
          autoComplete="off"
          name={name}
        />
        <button type="button" onClick={onToggle}
          className="absolute right-3 top-1/2 -translate-y-1/2 opacity-50 hover:opacity-100"
          style={{ background: "none", border: "none", cursor: "pointer" }}>
          {show ? <EyeOff size={14} /> : <Eye size={14} />}
        </button>
      </div>
    </div>
  );
}

// FIX 2026-07-31: this used to be ONE panel with ONE "Save API Keys" button
// covering all four fields. GET returns MASKED display values ("abcd…wxyz"),
// which got loaded as the form's starting point — the old save() sent the
// whole object every time, so editing only the Alpaca fields silently
// re-saved the Tradier key AS its own masked display string (and vice
// versa), replacing a real credential with garbage. That's what broke
// Tradier (268 silent 401s) and then, independently, crashed Alpaca calls
// outright — the masked "…" character isn't valid latin-1, so any HTTP
// library that encodes headers as latin-1 throws on it. A single shared
// button also visually implied "fill in both," which is exactly backwards:
// touching one broker's fields should never be able to affect the other's.
// Fix: two fully independent panels below, each with its own load, its own
// "touched" tracking, and its own Save button that only ever sends ITS OWN
// two fields — an Alpaca save cannot include a Tradier field or vice versa,
// not just "won't accidentally," structurally can't.

function useCredentialSave<K extends string>(fields: K[]) {
  const [creds, setCreds]     = useState<Record<K, string>>(() => Object.fromEntries(fields.map(f => [f, ""])) as Record<K, string>);
  const [touched, setTouched] = useState<Partial<Record<K, boolean>>>({});
  const [status, setStatus]   = useState<{ ok?: boolean; msg?: string } | null>(null);
  const [loaded, setLoaded]   = useState(false);

  useEffect(() => {
    (async () => {
      try {
        const r = await fetch("/api/settings/credentials", { credentials: "include" });
        if (r.ok) {
          const d = await r.json();
          setCreds(c => {
            const next = { ...c };
            for (const f of fields) next[f] = d[f] || "";
            return next;
          });
        }
      } catch { /* ignore */ }
      setLoaded(true);
    })();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  function setField(key: K, v: string) {
    setCreds(c => ({ ...c, [key]: v }));
    setTouched(t => ({ ...t, [key]: true }));
  }

  async function save(label: string) {
    setStatus(null);
    const payload: Partial<Record<K, string>> = {};
    for (const key of fields) if (touched[key]) payload[key] = creds[key];
    if (Object.keys(payload).length === 0) {
      setStatus({ ok: true, msg: "Nothing changed." });
      setTimeout(() => setStatus(null), 3000);
      return;
    }
    try {
      const r = await fetch("/api/settings/credentials", {
        method: "POST", credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || "Save failed");
      setStatus({ ok: true, msg: `${label} saved.` });
      setTouched({});
    } catch (e: any) {
      setStatus({ ok: false, msg: e.message || "Save failed" });
    }
    setTimeout(() => setStatus(null), 3000);
  }

  return { creds, setField, status, loaded, save };
}

function AlpacaCredentialsPanel() {
  const [show, setShow] = useState({ key: false, secret: false });
  const { creds, setField, status, loaded, save } =
    useCredentialSave<"alpaca_api_key" | "alpaca_secret_key">(["alpaca_api_key", "alpaca_secret_key"]);

  if (!loaded) return <p className="text-xs" style={{ color: "var(--ink-muted)" }}>Loading…</p>;

  return (
    <div className="card p-4 flex flex-col gap-3">
      <div className="flex items-center gap-2">
        <Key size={14} style={{ color: "var(--accent)" }} />
        <h3 className="text-sm font-semibold" style={{ color: "var(--ink)" }}>Alpaca</h3>
      </div>
      <p className="text-xs" style={{ color: "var(--ink-muted)" }}>
        Same key pair for paper and live — only the URL changes when you toggle modes. Saving
        here never touches your Tradier keys.
      </p>
      <CredentialField label="Alpaca API Key" name="alpaca_key"
        value={creds.alpaca_api_key} onChange={v => setField("alpaca_api_key", v)}
        show={show.key} onToggle={() => setShow(s => ({ ...s, key: !s.key }))}
        hint="PK…" />
      <CredentialField label="Alpaca Secret Key" name="alpaca_secret"
        value={creds.alpaca_secret_key} onChange={v => setField("alpaca_secret_key", v)}
        show={show.secret} onToggle={() => setShow(s => ({ ...s, secret: !s.secret }))} />
      {status && (
        <p className="text-xs font-medium" style={{ color: status.ok ? "var(--accent)" : "#f87171" }}>{status.msg}</p>
      )}
      <button className="btn btn-primary" onClick={() => save("Alpaca keys")}>
        <Save size={14} /> Save Alpaca Keys
      </button>
    </div>
  );
}

function TradierCredentialsPanel() {
  const [show, setShow] = useState(false);
  const { creds, setField, status, loaded, save } =
    useCredentialSave<"tradier_api_key" | "tradier_account_id">(["tradier_api_key", "tradier_account_id"]);

  if (!loaded) return <p className="text-xs" style={{ color: "var(--ink-muted)" }}>Loading…</p>;

  return (
    <div className="card p-4 flex flex-col gap-3">
      <div className="flex items-center gap-2">
        <Key size={14} style={{ color: "var(--accent)" }} />
        <h3 className="text-sm font-semibold" style={{ color: "var(--ink)" }}>Tradier</h3>
      </div>
      <p className="text-xs" style={{ color: "var(--ink-muted)" }}>
        Used for options quotes and chains. Saving here never touches your Alpaca keys.
      </p>
      <CredentialField label="Tradier API Key" name="tradier_key"
        value={creds.tradier_api_key} onChange={v => setField("tradier_api_key", v)}
        show={show} onToggle={() => setShow(s => !s)}
        hint="Bearer token from Tradier dashboard" />
      <CredentialField label="Tradier Account ID" name="tradier_account_id"
        value={creds.tradier_account_id} onChange={v => setField("tradier_account_id", v)}
        show={true} onToggle={() => {}} hint="Account number (digits only)" />
      {status && (
        <p className="text-xs font-medium" style={{ color: status.ok ? "var(--accent)" : "#f87171" }}>{status.msg}</p>
      )}
      <button className="btn btn-primary" onClick={() => save("Tradier keys")}>
        <Save size={14} /> Save Tradier Keys
      </button>
    </div>
  );
}

export function Settings() {
  const [form,      setForm]      = useState<AppSettings>(DEFAULT);
  const [savedForm, setSavedForm] = useState<AppSettings>(DEFAULT); // last committed state
  const [saved,     setSaved]     = useState(false);
  // Raw watchlist text — only parsed into form.watchlist on blur so commas
  // don't disappear while the user is still typing
  const [watchlistRaw, setWatchlistRaw] = useState(DEFAULT.watchlist.join(", "));
  const qc = useQueryClient();

  const { data } = useQuery({
    queryKey: ["settings"],
    queryFn: api.settings.get,
  });

  useEffect(() => {
    if (data) {
      setForm(data);
      setSavedForm(data);   // anchor the "discard" reference
      setWatchlistRaw(data.watchlist.join(", "));
    }
  }, [data]);

  function set<K extends keyof AppSettings>(key: K, val: AppSettings[K]) {
    setForm((f) => ({ ...f, [key]: val }));
    setSaved(false);
  }

  // True when the form has been changed since the last save/load
  const hasChanges = JSON.stringify(form) !== JSON.stringify(savedForm);

  function discard() {
    setForm(savedForm);
    setWatchlistRaw(savedForm.watchlist.join(", "));
  }

  async function save() {
    await api.settings.save(form);
    setSavedForm(form);   // move the anchor forward so discard stays correct
    qc.invalidateQueries({ queryKey: ["settings"] });
    setSaved(true);
    setTimeout(() => setSaved(false), 2500);
  }

  return (
    <div className="p-4 max-w-2xl flex flex-col gap-4">
      {/* Trading Mode */}
      <div className="card p-4">
        <h3 className="text-sm font-semibold mb-1" style={{ color: "var(--ink)" }}>Trading mode</h3>
        <p className="text-xs mb-3" style={{ color: "var(--ink-muted)" }}>
          Controls whether the bot places real orders or simulated paper trades. Takes effect on next bot start.
        </p>
        <div className="flex gap-2">
          {(["paper", "live"] as const).map((m) => (
            <button
              key={m}
              onClick={() => set("paper_trading" as any, m === "paper")}
              className={`btn flex-1 justify-center ${(form as any).paper_trading === (m === "paper") ? "btn-primary" : "btn-ghost"}`}
              style={{ textTransform: "capitalize" }}
            >
              {m === "paper" ? "📄 Paper" : "⚡ Live"}
            </button>
          ))}
        </div>
        {(form as any).paper_trading === false && (
          <p className="text-xs mt-2" style={{ color: "#f87171" }}>
            ⚠️ Live mode places real orders with real money. Ensure your Alpaca live API keys are configured.
          </p>
        )}

        {/* Execution mode — signal-only vs auto-execute */}
        <div className="mt-3 pt-3" style={{ borderTop: "1px solid var(--border)" }}>
          <Toggle
            label="Signal-Only mode — bot signals but does NOT place orders"
            checked={form.signal_only_mode ?? false}
            onChange={(v) => set("signal_only_mode" as any, v)}
          />
          {(form.signal_only_mode) && (
            <p className="text-xs mt-1" style={{ color: "var(--warning)" }}>
              ⚠️ Signal-Only is ON. The bot will alert you to every entry but will NOT submit any orders. Switch off to enable auto-execution.
            </p>
          )}
        </div>
      </div>

      {/* Risk */}
      <div className="card p-4">
        <h3 className="text-sm font-semibold mb-3" style={{ color: "var(--ink)" }}>Risk</h3>

        <div className="flex flex-col gap-3">
          <div className="flex items-center justify-between gap-4">
            <label className="text-sm" style={{ color: "var(--ink)" }}>
              Risk per trade (%)
            </label>
            <input
              type="number"
              step="0.1"
              min="0.1"
              max="5"
              value={form.risk_pct}
              disabled={form.risk_auto}
              onChange={(e) => {
                set("risk_pct", parseFloat(e.target.value));
                set("risk_auto", false);
              }}
              className="input w-24"
            />
          </div>

          <Toggle
            label="Automatic risk tier (based on account balance)"
            checked={form.risk_auto ?? true}
            onChange={(v) => set("risk_auto", v)}
          />

          <div className="flex items-center justify-between gap-4">
            <label className="text-sm" style={{ color: "var(--ink)" }}>
              Max concurrent positions
            </label>
            <input
              type="number"
              min="1"
              max="5"
              value={form.max_concurrent_positions}
              onChange={(e) => set("max_concurrent_positions", parseInt(e.target.value))}
              className="input w-24"
            />
          </div>

          <div className="flex items-center justify-between gap-4">
            <label className="text-sm" style={{ color: "var(--ink)" }}>R:R ratio mode</label>
            <select
              className="select w-40"
              value={form.rr_ratio_mode}
              onChange={(e) => set("rr_ratio_mode", e.target.value)}
            >
              <option value="auto">Automatic</option>
              <option value="small_account">Small account (1.2:1 minimum)</option>
              <option value="professional">Professional (1.6:1 minimum)</option>
            </select>
          </div>

          <Toggle
            label="Growth mode (reinvest profits)"
            checked={form.growth_mode}
            onChange={(v) => set("growth_mode", v)}
          />
          <Toggle
            label="Flip trading (long → short on breakdown)"
            checked={form.flip_trading_enabled}
            onChange={(v) => set("flip_trading_enabled", v)}
          />
        </div>
      </div>

      {/* Strategies */}
      <div className="card p-4">
        <h3 className="text-sm font-semibold mb-3" style={{ color: "var(--ink)" }}>Strategies</h3>
        <Toggle label="ORB — Opening Range Breakout (9:30–9:44)" checked={form.orb_enabled}
                onChange={(v) => set("orb_enabled", v)} />
        <Toggle label="VWAP Pullback (all session)" checked={form.vwap_pullback_enabled}
                onChange={(v) => set("vwap_pullback_enabled", v)} />
        <Toggle label="Fair Value Gap / FVG (all session)" checked={form.fvg_enabled}
                onChange={(v) => set("fvg_enabled", v)} />
        <Toggle label="Inverted FVG / IFVG — zone-flip reversal (all session)" checked={form.ifvg_enabled}
                onChange={(v) => set("ifvg_enabled", v)} />
        <div className="flex items-center justify-between gap-3 py-2">
          <span className="text-sm" style={{ color: "var(--ink-muted)" }}>
            Channel Breakout
            <span className="block text-xs mt-0.5">
              Not active in the live router; this setting cannot enable it.
            </span>
          </span>
          <span className="badge" style={{ background: "var(--surface-raised)", color: "var(--ink-muted)" }}>
            INACTIVE
          </span>
        </div>
        <div className="flex items-center justify-between gap-3 py-2">
          <span className="text-sm" style={{ color: "var(--ink-muted)" }}>
            BOS / MSS
            <span className="block text-xs mt-0.5">
              Its sweep/structure confirmation is incorporated into FVG, not run as a separate strategy.
            </span>
          </span>
          <span className="badge" style={{ background: "var(--surface-raised)", color: "var(--ink-muted)" }}>
            INTEGRATED
          </span>
        </div>
        <Toggle label="Mid-Day Breakdown / MID_BRK — OFF by default (no edge in 13 backtested configs, 2026-07-23 audit)"
                checked={form.mid_brk_enabled}
                onChange={(v) => set("mid_brk_enabled", v)} />
        <Toggle label="Trend Continuation / TREND_CONT (9:45 AM – 2:30 PM)" checked={form.trend_cont_enabled}
                onChange={(v) => set("trend_cont_enabled", v)} />
        <Toggle label="Afternoon Reversal / AFT_REV (1:00 PM – 3:30 PM)" checked={form.aft_rev_enabled}
                onChange={(v) => set("aft_rev_enabled", v)} />
        <Toggle label="Gap and Go / GAP_GO (9:30–9:45 AM) — trades the continuation of a pre-market gap if price pushes past its own opening bar in the gap direction"
                checked={form.gap_go_enabled ?? true}
                onChange={(v) => set("gap_go_enabled", v)} />
        <Toggle label="Liquidity Sweep Reversal / LIQ_SWEEP (9:45 AM – 3:30 PM) — fades a swept swing high/low"
                checked={form.liquidity_sweep_enabled ?? true}
                onChange={(v) => set("liquidity_sweep_enabled", v)} />
      </div>

      {/* Display */}
      <div className="card p-4">
        <h3 className="text-sm font-semibold mb-3" style={{ color: "var(--ink)" }}>Display</h3>
        <div className="flex items-center justify-between gap-4">
          <label className="text-sm" style={{ color: "var(--ink)" }}>
            Timezone
            <span className="block text-xs mt-0.5" style={{ color: "var(--ink-muted)" }}>
              Used for chart timestamps and log times
            </span>
          </label>
          <select
            className="select w-56"
            value={form.display_timezone ?? "America/New_York"}
            onChange={(e) => set("display_timezone", e.target.value)}
          >
            {TIMEZONES.map((tz) => (
              <option key={tz.value} value={tz.value}>{tz.label}</option>
            ))}
          </select>
        </div>
      </div>

      {/* Trade Parameters */}
      <div className="card p-4">
        <h3 className="text-sm font-semibold mb-1" style={{ color: "var(--ink)" }}>Trade Parameters</h3>
        <p className="text-xs mb-3" style={{ color: "var(--ink-muted)" }}>
          Live-tuning — changes apply on the next bot tick (&lt;60 s). No restart needed.
        </p>
        {form.simplified_exit_mode && (
          <p className="text-xs mb-3" style={{ color: "var(--warning)" }}>
            Simplified Exit is active: positions use a hard stop, underlying Chandelier exit, and time cap.
            Stage-1 partial-profit settings apply only when Simplified Exit is off.
          </p>
        )}
        <div className="flex flex-col gap-3">
          <div className="flex items-center justify-between gap-4">
            <label className="text-sm" style={{ color: "var(--ink)" }}>
              Stage-1 target (% gain)
              <span className="block text-xs mt-0.5" style={{ color: "var(--ink-muted)" }}>
                Used only with Simplified Exit off: sell 50% once the option gains this much (default 50%)
              </span>
            </label>
            <input
              type="number" step="5" min="15" max="100"
              value={form.orb_stage1_gain_pct ?? 50}
              onChange={(e) => set("orb_stage1_gain_pct", parseFloat(e.target.value))}
              className="input w-24"
            />
          </div>
          <div className="flex items-center justify-between gap-4">
            <label className="text-sm" style={{ color: "var(--ink)" }}>
              Stop-loss (% loss)
              <span className="block text-xs mt-0.5" style={{ color: "var(--ink-muted)" }}>
                Exit if option premium falls this much from entry (default 20%)
              </span>
            </label>
            <input
              type="number" step="5" min="5" max="50"
              value={form.orb_stop_loss_pct ?? 20}
              onChange={(e) => set("orb_stop_loss_pct", parseFloat(e.target.value))}
              className="input w-24"
            />
          </div>
          <div className="flex items-center justify-between gap-4">
            <label className="text-sm" style={{ color: "var(--ink)" }}>
              Spread gate (% of mid)
              <span className="block text-xs mt-0.5" style={{ color: "var(--ink-muted)" }}>
                Skip contracts wider than this bid-ask spread (default 8%)
              </span>
            </label>
            <input
              type="number" step="5" min="5" max="50"
              value={form.spread_gate_pct ?? 8}
              onChange={(e) => set("spread_gate_pct", parseFloat(e.target.value))}
              className="input w-24"
            />
          </div>
          <div className="flex items-center justify-between gap-4">
            <label className="text-sm" style={{ color: "var(--ink)" }}>
              Volume ROC threshold
              <span className="block text-xs mt-0.5" style={{ color: "var(--ink-muted)" }}>
                Veto signals if recent vol is below this fraction of prior vol (default 0.50)
              </span>
            </label>
            <input
              type="number" step="0.05" min="0.10" max="0.90"
              value={form.vol_roc_threshold ?? 0.50}
              onChange={(e) => set("vol_roc_threshold", parseFloat(e.target.value))}
              className="input w-24"
            />
          </div>
          <div className="flex items-center justify-between gap-4">
            <label className="text-sm" style={{ color: "var(--ink)" }}>
              Daily loss hard cap (%)
              <span className="block text-xs mt-0.5" style={{ color: "var(--ink-muted)" }}>
                Freezes ALL trading for 24h if breached (default 10%). Was
                hardcoded until 2026-07-24 — lower it carefully, small accounts
                can trip a tight cap on normal option premium swings.
              </span>
            </label>
            <input
              type="number" step="1" min="3" max="30"
              value={form.daily_loss_hard_cap_pct ?? 10}
              onChange={(e) => set("daily_loss_hard_cap_pct", parseFloat(e.target.value))}
              className="input w-24"
            />
          </div>
          <div className="flex items-center justify-between gap-4">
            <label className="text-sm" style={{ color: "var(--ink)" }}>
              Minimum entry grade
              <span className="block text-xs mt-0.5" style={{ color: "var(--ink-muted)" }}>
                Block entries on tickers graded below this (matches the Daily
                Brief's premarket grade). Off by default — was display-only
                until 2026-07-24.
              </span>
            </label>
            <div className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={form.min_grade_filter_enabled ?? false}
                onChange={(e) => set("min_grade_filter_enabled", e.target.checked)}
              />
              <select
                value={form.min_entry_grade ?? "C"}
                onChange={(e) => set("min_entry_grade", e.target.value)}
                disabled={!(form.min_grade_filter_enabled ?? false)}
                className="input w-24"
              >
                <option value="A+">A+</option>
                <option value="A">A</option>
                <option value="B">B</option>
                <option value="C">C</option>
                <option value="Watch">Watch</option>
              </select>
            </div>
          </div>
          <div className="flex items-center justify-between gap-4">
            <label className="text-sm" style={{ color: "var(--ink)" }}>
              Max spend per contract (% of balance)
              <span className="block text-xs mt-0.5" style={{ color: "var(--ink-muted)" }}>
                The real affordability cap — separate from risk %. A signal
                gets skipped if the cheapest contract costs more than this.
                Was hardcoded 15% with no UI until 2026-07-24.
              </span>
            </label>
            <input
              type="number" step="1" min="5" max="100"
              value={form.max_position_dollars_pct ?? 15}
              onChange={(e) => set("max_position_dollars_pct", parseFloat(e.target.value))}
              className="input w-24"
            />
          </div>
        </div>
      </div>

      {/* Exit engine — controls how an OPEN position gets closed */}
      <div className="card p-4">
        <h3 className="text-sm font-semibold mb-1" style={{ color: "var(--ink)" }}>Exit engine</h3>
        <p className="text-xs mb-3" style={{ color: "var(--ink-muted)" }}>
          Controls how the bot closes a position once it's already open.
          Only one exit engine ever runs at a time.
        </p>
        <Toggle
          label="Simplified exit (hard stop / 3.0x chandelier trail / time cap)"
          checked={form.simplified_exit_mode ?? true}
          onChange={(v) => set("simplified_exit_mode", v)}
        />
        <p className="text-xs" style={{ color: "var(--ink-muted)" }}>
          On (default): the 3-rule exit that beat the full 9-condition engine
          on realized R:R in backtesting. Off: falls back to the full engine.
        </p>
      </div>

      {/* Entry confirmation — controls whether a trade gets taken at all */}
      <div className="card p-4">
        <h3 className="text-sm font-semibold mb-1" style={{ color: "var(--ink)" }}>Entry confirmation</h3>
        <p className="text-xs mb-3" style={{ color: "var(--ink-muted)" }}>
          Runs before a trade is entered, not after — adjusts a signal's
          confidence rather than closing anything.
        </p>
        <Toggle
          label="MTF confirmation gate (live 1Hour bias check)"
          checked={form.mtf_confirmation_enabled ?? true}
          onChange={(v) => set("mtf_confirmation_enabled", v)}
        />
        <p className="text-xs" style={{ color: "var(--ink-muted)" }}>
          Unlike every other gate, this depends on a live "as-of-now" API
          fetch and can't be validated against the backtester.
        </p>
        <Toggle
          label="INST_ORB immediate entry (skip retest wait)"
          checked={form.inst_orb_immediate_entry_enabled ?? true}
          onChange={(v) => set("inst_orb_immediate_entry_enabled", v)}
        />
        <p className="text-xs" style={{ color: "var(--ink-muted)" }}>
          INST_ORB normally waits for price to pull back and retest the
          opening-range level before entering — cheaper premium, tighter
          stop. On: it can also enter right on the breakout bar itself if
          RVOL and cooldown gates clear, so moves that never come back to
          retest aren't missed entirely. The retest path still runs as a
          fallback either way. Not backtested — this is a live trade-off
          between catching more moves and worse fills.
        </p>
      </div>

      {/* Watchlist */}
      <div className="card p-4">
        <h3 className="text-sm font-semibold mb-3" style={{ color: "var(--ink)" }}>Watchlist</h3>
        <textarea
          className="input w-full font-mono text-sm"
          rows={3}
          value={watchlistRaw}
          onChange={(e) => setWatchlistRaw(e.target.value)}
          onBlur={(e) =>
            set("watchlist", e.target.value.split(",").map((t) => t.trim().toUpperCase()).filter(Boolean))
          }
          placeholder="SPY, QQQ, NVDA…"
        />
        <p className="text-xs mt-1" style={{ color: "var(--ink-muted)" }}>
          Comma-separated tickers. Scanner may override this during market hours.
        </p>
      </div>

      {/* API Credentials — two independent panels, see the comment above
          AlpacaCredentialsPanel for why they're structurally separate now */}
      <p className="text-xs font-semibold px-1" style={{ color: "var(--ink-muted)" }}>
        API Credentials — each saves independently
      </p>
      <AlpacaCredentialsPanel />
      <TradierCredentialsPanel />
      <p className="text-xs px-1" style={{ color: "var(--ink-muted)" }}>
        Keys are encrypted at rest (AES-128 / Fernet). Never stored in plain text.
      </p>

      {/* Save / Discard */}
      <div className="flex gap-2">
        {hasChanges && (
          <button
            className="btn btn-ghost flex-none"
            onClick={discard}
            title="Revert all unsaved changes back to the last saved state"
          >
            Discard changes
          </button>
        )}
        <button
          className={`btn flex-1 justify-center ${saved ? "btn-ghost" : hasChanges ? "btn-primary" : "btn-ghost"}`}
          onClick={save}
        >
          <Save size={14} />
          {saved ? "Saved!" : "Save Settings"}
        </button>
      </div>
    </div>
  );
}
