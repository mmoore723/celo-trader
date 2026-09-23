/**
 * Settings.tsx — Bot configuration form + API credentials.
 */
import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Save, Eye, EyeOff, Key, CheckCircle, AlertTriangle } from "lucide-react";
import { api, type AppSettings, type ReviewedStrategyCatalogEntry } from "../lib/api";
import { loadCredentialDisplay, maskCredentialForDisplay } from "../lib/credentialDisplay.js";
import { needsTradierSandbox } from "../lib/connectionHealthView.js";
import { TestedStrategies } from "../components/settings/TestedStrategies";
import { StrategyRecommendations, type PairDecision } from "../components/settings/StrategyRecommendations";
import type { StrategyTickerRecommendation } from "../lib/api";
import { PairEvidence } from "../components/settings/PairEvidence";
import { ClosedTradeEvidence } from "../components/settings/ClosedTradeEvidence";
import { StrategyToggleCard, Toggle } from "../components/settings/StrategyToggleCard";
import { StrategyExitNotice } from "../components/settings/StrategyExitNotice";
import { StrategyIdentity } from "../components/settings/StrategyIdentity";
import { strategyName } from "../lib/strategyIdentity.js";

const DEFAULT: AppSettings = {
  broker_provider: "alpaca",
  paper_trading: true,
  risk_pct: 5.0,
  risk_auto: true,
  growth_mode: false,
  flip_trading_enabled: true,
  max_concurrent_positions: 2,
  rr_ratio_mode: "auto",
  watchlist: ["SPY"],
  validated_strategy_ids: [],
  strategy_orb_pullback_v2_enabled: true,
  strategy_spy_trend_cont_v2_enabled: true,
  strategy_spy_afternoon_fvg_v2_enabled: true,
  strategy_spy_failed_range_recovery_v2_enabled: true,
  strategy_tsla_two_leg_trend_pullback_v2_enabled: true,
  observe_ctx_orb_nr7_inside_enabled: true,
  observe_ctx_orb_atr10_enabled: true,
  observe_ctx_vwap_ker_enabled: true,
  observe_ctx_vwap_displacement_enabled: true,
  observe_ctx_squeeze_macd_enabled: true,
  research_strategy_ids: [
    "V2_AFTERNOON_COMPRESSION_BREAKOUT",
    "V2_AFTERNOON_REVERSAL", "V2_EMA_PULLBACK_RTH", "V2_FAIR_VALUE_GAP",
    "V2_GAP_FILL_RTH", "V2_MIDDAY_BREAKDOWN", "V2_IMPULSE_ANCHORED_VWAP_PULLBACK",
    "V2_OPENING_MOMENTUM_RTH_EXPLORATORY",
    "V2_ORB_CONFIRMED_BREAKOUT", "V2_RANGE_SWEEP_RECLAIM",
    "V2_SPY_ORB_RSI_MACD_SHORT", "V2_TREND_CONT",
    "V2_TURTLE_SOUP_RTH", "V2_VWAP_PULLBACK", "V2_VWAP_REVERSION_RTH",
    "TV_SUPERTREND_REVERSAL_V4",
  ],
  opportunity_tier_enabled: false,
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
  simplified_exit_mode: true, // Read-only compatibility value, never an exit selector.
  mtf_confirmation_enabled: true,
};

const TIMEZONES = [
  { value: "America/New_York",    label: "Eastern (ET) — NYSE hours" },
  { value: "America/Chicago",     label: "Central (CT)" },
  { value: "America/Denver",      label: "Mountain (MT)" },
  { value: "America/Los_Angeles", label: "Pacific (PT)" },
  { value: "America/Phoenix",     label: "Arizona (MST, no DST)" },
  { value: "UTC",                 label: "UTC" },
];

const evidenceDate = (value?: string) => value
  ? new Date(`${value}T12:00:00`).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })
  : "";

// ── Credentials panel ──────────────────────────────────────────────────────
function CredentialField({
  label, name, value, onChange, show, onToggle, hint, savedMask
}: {
  label: string; name: string; value: string;
  onChange: (v: string) => void; show: boolean;
  onToggle: () => void; hint?: string; savedMask?: string;
}) {
  return (
    <div className="flex flex-col gap-1">
      <label className="text-xs font-medium" style={{ color: "var(--ink-muted)" }}>{label}</label>
      <div className="relative">
        <input
          type={show ? "text" : "password"}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={savedMask ? `Saved (${savedMask}) — enter a new value to replace` : (hint || "Enter key…")}
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
// fields — an Alpaca save cannot include a Tradier field or vice versa,
// not just "won't accidentally," structurally can't.

function useCredentialSave<K extends string>(fields: K[], secretFields: K[] = []) {
  const [creds, setCreds]     = useState<Record<K, string>>(() => Object.fromEntries(fields.map(f => [f, ""])) as Record<K, string>);
  const [touched, setTouched] = useState<Partial<Record<K, boolean>>>({});
  const [savedMasks, setSavedMasks] = useState<Partial<Record<K, string>>>({});
  const [status, setStatus]   = useState<{ ok?: boolean; msg?: string } | null>(null);
  const [loaded, setLoaded]   = useState(false);

  useEffect(() => {
    (async () => {
      try {
        const r = await fetch("/api/settings/credentials", { credentials: "include" });
        if (r.ok) {
          const d = await r.json();
          const loadedDisplay = loadCredentialDisplay(fields, secretFields, d);
          setCreds(loadedDisplay.values);
          setSavedMasks(loadedDisplay.savedMasks);
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
    const changedKeys = fields.filter(key => touched[key]);
    for (const key of changedKeys) payload[key] = creds[key];
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
      setStatus({ ok: true, msg: d.message || `${label} saved.` });
      setCreds(current => {
        const next = { ...current };
        for (const key of changedKeys) {
          if (secretFields.includes(key)) next[key] = "";
        }
        return next;
      });
      setSavedMasks(current => {
        const next = { ...current };
        for (const key of changedKeys) {
          if (secretFields.includes(key)) {
            const mask = maskCredentialForDisplay(creds[key]);
            if (mask) next[key] = mask;
            else delete next[key];
          }
        }
        return next;
      });
      setTouched({});
    } catch (e: any) {
      setStatus({ ok: false, msg: e.message || "Save failed" });
    }
    setTimeout(() => setStatus(null), 3000);
  }

  return { creds, savedMasks, setField, status, loaded, save };
}

function AlpacaCredentialsPanel() {
  const [show, setShow] = useState({ key: false, secret: false });
  const { creds, savedMasks, setField, status, loaded, save } =
    useCredentialSave<"alpaca_api_key" | "alpaca_secret_key">(
      ["alpaca_api_key", "alpaca_secret_key"],
      ["alpaca_api_key", "alpaca_secret_key"],
    );

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
        savedMask={savedMasks.alpaca_api_key}
        hint="PK…" />
      <CredentialField label="Alpaca Secret Key" name="alpaca_secret"
        value={creds.alpaca_secret_key} onChange={v => setField("alpaca_secret_key", v)}
        show={show.secret} onToggle={() => setShow(s => ({ ...s, secret: !s.secret }))}
        savedMask={savedMasks.alpaca_secret_key} />
      {status && (
        <p className="text-xs font-medium" style={{ color: status.ok ? "var(--accent)" : "#f87171" }}>{status.msg}</p>
      )}
      <button className="btn btn-primary" onClick={() => save("Alpaca keys")}>
        <Save size={14} /> Save Alpaca Keys
      </button>
    </div>
  );
}

function TradierCredentialsPanel({ provider, paper }: { provider: string; paper: boolean }) {
  const [show, setShow] = useState({ sandbox: false, live: false });
  const showSandbox = needsTradierSandbox(provider, paper);
  const { creds, savedMasks, setField, status, loaded, save } =
    useCredentialSave<"tradier_api_key" | "tradier_market_api_key" | "tradier_account_id" | "tradier_live_account_id">(
      ["tradier_api_key", "tradier_market_api_key", "tradier_account_id", "tradier_live_account_id"],
      ["tradier_api_key", "tradier_market_api_key"],
    );

  if (!loaded) return <p className="text-xs" style={{ color: "var(--ink-muted)" }}>Loading…</p>;

  return (
    <div className="card p-4 flex flex-col gap-3">
      <div className="flex items-center gap-2">
        <Key size={14} style={{ color: "var(--accent)" }} />
        <h3 className="text-sm font-semibold" style={{ color: "var(--ink)" }}>Tradier</h3>
      </div>
      <p className="text-xs" style={{ color: "var(--ink-muted)" }}>
        {provider === "alpaca"
          ? `Tradier supplies current prices. Orders stay with Alpaca ${paper ? "Paper" : "Live"}.`
          : paper
            ? "Production supplies current prices; Sandbox handles Tradier paper orders."
            : "Production supplies current prices and handles Tradier live orders."}
        {" "}Saving a token does not change your broker or trading mode.
      </p>
      {showSandbox && <>
      <CredentialField label="Sandbox token (only for Tradier Paper orders)" name="tradier_key"
        value={creds.tradier_api_key} onChange={v => setField("tradier_api_key", v)}
        show={show.sandbox} onToggle={() => setShow(s => ({ ...s, sandbox: !s.sandbox }))}
        savedMask={savedMasks.tradier_api_key}
        hint="Sandbox bearer token" />
      <CredentialField label="Sandbox account ID (only for Tradier Paper)" name="tradier_account_id"
        value={creds.tradier_account_id} onChange={v => setField("tradier_account_id", v)}
        show={true} onToggle={() => {}} hint="Sandbox account number" />
      </>}
      <CredentialField label="Production token (current prices)" name="tradier_market_key"
        value={creds.tradier_market_api_key} onChange={v => setField("tradier_market_api_key", v)}
        show={show.live} onToggle={() => setShow(s => ({ ...s, live: !s.live }))}
        savedMask={savedMasks.tradier_market_api_key}
        hint="Production bearer token" />
      {provider === "tradier" && !paper && <CredentialField label="Live account ID" name="tradier_live_account_id"
        value={creds.tradier_live_account_id} onChange={v => setField("tradier_live_account_id", v)}
        show={true} onToggle={() => {}} hint="Live account number" />}
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
  const [searchParams, setSearchParams] = useSearchParams();
  const activeTab = searchParams.get("tab") === "strategies" ? "strategies" : "general";
  function setActiveTab(tab: "general" | "strategies") {
    setSearchParams(previous => { const next = new URLSearchParams(previous); next.set("tab", tab); return next; }, { replace: true });
  }
  const [form,      setForm]      = useState<AppSettings>(DEFAULT);
  const [savedForm, setSavedForm] = useState<AppSettings>(DEFAULT); // last committed state
  const [saved,     setSaved]     = useState(false);
  const [saveError, setSaveError] = useState("");
  // Raw watchlist text — only parsed into form.watchlist on blur so commas
  // don't disappear while the user is still typing
  const [watchlistRaw, setWatchlistRaw] = useState(DEFAULT.watchlist.join(", "));
  const qc = useQueryClient();

  const { data } = useQuery({
    queryKey: ["settings"],
    queryFn: api.settings.get,
  });
  const { data: strategyCatalog } = useQuery({
    queryKey: ["strategy-catalog"],
    queryFn: api.settings.strategies,
  });
  // Evidence belongs to the last saved broker/mode, not an unsaved form choice
  // the user may still discard.
  const actualAccountMode = (data?.paper_trading ?? form.paper_trading) ? "paper" : "live";
  const actualBrokerProvider = data?.broker_provider ?? form.broker_provider ?? "alpaca";
  const { data: closedTradeEvidence, isPending: closedTradesLoading, isError: closedTradesFailed } = useQuery({
    queryKey: ["settings-closed-trades", actualAccountMode, actualBrokerProvider],
    queryFn: api.settings.closedStrategyTrades,
    enabled: Boolean(data),
    refetchInterval: 60_000,
  });
  const { data: strategyResearch } = useQuery({
    queryKey: ["strategy-research-matrix"],
    queryFn: () => api.strategyHealth.researchMatrix(90),
    refetchInterval: 60_000,
  });
  const { data: strategyHistory } = useQuery({
    queryKey: ["strategy-setting-history"],
    queryFn: () => api.settings.strategyHistory(12),
  });
  const { data: strategyRecommendations, isPending: recommendationsLoading, isError: recommendationsFailed, refetch: refreshRecommendations } = useQuery({
    queryKey: ["strategy-recommendations"],
    queryFn: api.settings.recommendations,
  });
  const { data: brokerReadiness, refetch: refreshBrokerReadiness, isFetching: checkingBroker } = useQuery({
    queryKey: ["broker-readiness", form.paper_trading ?? true],
    queryFn: () => api.settings.brokerReadiness(form.paper_trading ?? true),
    refetchOnWindowFocus: false,
    enabled: (form.broker_provider ?? "alpaca") === "tradier",
  });

  async function decideRecommendation(item: StrategyTickerRecommendation, decision: PairDecision) {
    await api.settings.decidePair(item, decision);
    qc.invalidateQueries({ queryKey: ["strategy-recommendations"] });
    qc.invalidateQueries({ queryKey: ["strategy-research-matrix"] });
    qc.invalidateQueries({ queryKey: ["strategy-catalog"] });
    qc.invalidateQueries({ queryKey: ["settings"] });
  }

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

  function strategyControl(strategy: ReviewedStrategyCatalogEntry) {
    const switchEnabled = Boolean(form[strategy.setting_key]);
    const tradingTickers = switchEnabled ? (strategy.trading_tickers ?? []) : [];
    const pf = strategy.backtest?.profit_factor;
    const pfLabel = typeof pf === "number" ? pf.toFixed(2) : (pf || "not recorded");
    const target = strategy.backtest?.target_profit_factor ?? 1.5;
    const reliableTarget = strategy.backtest?.meets_target && strategy.evidence_grade === "passed_declared_holdout";
    const matrixStrategy = strategyResearch?.strategies.find(item => item.strategy_id === strategy.strategy_id);
    const currentPairs = (matrixStrategy?.pairs ?? []).filter(pair => strategy.tickers.includes(pair.ticker) || pair.tradable);
    const pairProof = currentPairs.length
      ? currentPairs.map(pair => {
          const factor = pair.profit_factor === "infinite" ? "∞" : typeof pair.profit_factor === "number" ? pair.profit_factor.toFixed(2) : "—";
          const pnl = `${pair.net_one_contract_pnl >= 0 ? "+" : "-"}$${Math.abs(pair.net_one_contract_pnl).toFixed(2)}`;
          return `${pair.ticker} PF ${factor} · ${pair.option_results} option result${pair.option_results === 1 ? "" : "s"} · ${pnl}`;
        }).join(" · ")
      : `PF — · 0 option results`;
    return (
      <StrategyToggleCard
        key={strategy.strategy_id}
        separated={false}
          label={strategyName(strategy.display_name)}
          checked={switchEnabled}
          onChange={(v) => set(strategy.setting_key, v)}
          disabled={strategy.integrity_errors.length > 0}
      >
        <StrategyIdentity id={strategy.strategy_id} version={strategy.version}
          tickers={strategy.observation_only ? [] : tradingTickers}
          label={strategy.observation_only ? "Research · All collected tickers" : tradingTickers.length ? "Trading on" : "No tickers enabled"} />
        {!strategy.observation_only && <ClosedTradeEvidence data={closedTradeEvidence}
          strategyId={strategy.strategy_id} failed={closedTradesFailed} loading={closedTradesLoading} />}
        <p className="text-xs pb-1" style={{ color: "var(--ink-muted)" }}>
          <strong style={{ color: reliableTarget ? "var(--positive)" : "var(--warning)" }}>{strategy.backtest?.historical_test_through ? `Tests through ${evidenceDate(strategy.backtest.historical_test_through)}` : "Recorded test"}: PF {pfLabel}</strong>{strategy.backtest?.trades != null ? ` · ${strategy.backtest.trades} results` : ""}
        </p>
        {!strategy.observation_only ? (
          <p className="text-xs pb-1" style={{ color: "var(--ink-muted)" }}>
            <strong>Current research · strategy exits:</strong> {pairProof}
          </p>
        ) : <p className="text-xs pb-1" style={{ color: "var(--ink-muted)" }}>
          <strong>{matrixStrategy?.exit_measurement?.pf_label ?? "Current PF"} {matrixStrategy?.current_evidence.profit_factor === "infinite" ? "∞" : typeof matrixStrategy?.current_evidence.profit_factor === "number" ? matrixStrategy.current_evidence.profit_factor.toFixed(2) : "—"}</strong> · {matrixStrategy?.current_evidence.option_results ?? 0} option results across all collected tickers
        </p>}
        <PairEvidence strategy={matrixStrategy} />
        <details className="text-xs pb-3" style={{ color: "var(--ink-muted)" }}>
          <summary className="cursor-pointer">Test dates and proof</summary>
          <p className="mt-1">Goal PF {target.toFixed(1)}{!strategy.observation_only ? ` · ${actualBrokerProvider === "tradier" ? "Tradier" : "Alpaca"} ${actualAccountMode} orders only on ${strategy.tickers.join(", ")}.` : ""}</p>
          <p className="mt-1">{strategy.backtest?.comparison || strategy.evidence}</p>
          {currentPairs.some(pair => pair.previous_version_rows > 0) && <p className="mt-1">Earlier-version setups remain saved but are not mixed into the current PF.</p>}
        </details>
        {strategy.integrity_errors.length > 0 && (
          <p className="text-xs pb-3" style={{ color: "#f87171" }}>
            Disabled because its code no longer matches the reviewed evidence.
          </p>
        )}
      </StrategyToggleCard>
    );
  }

  // True when the form has been changed since the last save/load
  const hasChanges = JSON.stringify(form) !== JSON.stringify(savedForm);

  function discard() {
    setForm(savedForm);
    setWatchlistRaw(savedForm.watchlist.join(", "));
  }

  async function save() {
    setSaveError("");
    try {
      const committed = await api.settings.save(form);
      setForm(committed);
      setSavedForm(committed);
      qc.invalidateQueries({ queryKey: ["settings"] });
      qc.invalidateQueries({ queryKey: ["strategy-catalog"] });
      qc.invalidateQueries({ queryKey: ["strategy-setting-history"] });
      qc.invalidateQueries({ queryKey: ["broker-readiness"] });
      setSaved(true);
      setTimeout(() => setSaved(false), 2500);
    } catch (error: any) {
      setSaveError(error?.message || "Settings could not be saved.");
    }
  }

  return (
    <div className="settings-page p-4 flex flex-col gap-4">
      <div role="tablist" aria-label="Settings sections" className="flex gap-2">
        {(["general", "strategies"] as const).map(tab => <button key={tab} role="tab"
          id={`settings-tab-${tab}`} aria-selected={activeTab === tab} aria-controls={`settings-panel-${tab}`}
          tabIndex={activeTab === tab ? 0 : -1}
          onKeyDown={event => {
            if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
            event.preventDefault();
            const next = event.key === "Home" ? "general" : event.key === "End" ? "strategies" : activeTab === "general" ? "strategies" : "general";
            setActiveTab(next);
            document.getElementById(`settings-tab-${next}`)?.focus();
          }}
          className={`btn ${activeTab === tab ? "btn-primary" : "btn-ghost"}`}
          onClick={() => setActiveTab(tab)}>{tab === "general" ? "General" : "Strategies"}</button>)}
      </div>
      <div hidden={activeTab !== "general"} id="settings-panel-general" role="tabpanel" aria-labelledby="settings-tab-general" className={activeTab === "general" ? "flex flex-col gap-4" : "hidden"}>
      <div className="settings-paired-grid">
      {recommendationsFailed ? <div className="card p-4 text-sm" role="alert">Recommendations could not load. <button className="btn btn-ghost" onClick={() => refreshRecommendations()}>Try again</button></div> : recommendationsLoading ? <p role="status" className="text-sm">Checking strategy recommendations…</p> : <StrategyRecommendations
        recommendations={strategyRecommendations?.recommendations ?? []}
        onDecision={decideRecommendation}
      />}
      </div>
      <div className="settings-paired-grid settings-general-columns">
      <section className="settings-control-stack" aria-label="Trading preferences">
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
        <div className="mt-3 pt-3" style={{ borderTop: "1px solid var(--border)" }}>
          <label className="text-sm font-medium" style={{ color: "var(--ink)" }}>Broker for entries and exits</label>
          <div className="flex gap-2 mt-2">
            {(["alpaca", "tradier"] as const).map((provider) => (
              <button
                key={provider}
                onClick={() => set("broker_provider", provider)}
                className={`btn flex-1 justify-center ${(form.broker_provider ?? "alpaca") === provider ? "btn-primary" : "btn-ghost"}`}
              >
                {provider === "alpaca" ? "Alpaca" : "Tradier only"}
              </button>
            ))}
          </div>
          {(form.broker_provider ?? "alpaca") === "alpaca" && (
            <div className="mt-3 rounded-lg p-3 text-xs" style={{ background: "var(--surface-raised)", border: "1px solid var(--border)" }}>
              <div className="flex items-center gap-2 font-semibold" style={{ color: "var(--warning)" }}>
                <AlertTriangle size={14} /> Cross-broker paper test
              </div>
              <p className="mt-1" style={{ color: "var(--ink-muted)" }}>
                Option selection uses Tradier prices while orders fill in Alpaca. We measure the difference, but these results are not apples-to-apples with Tradier execution and cannot qualify the bot for live money.
              </p>
            </div>
          )}
          {(form.broker_provider ?? "alpaca") === "tradier" && (
            <div className="mt-3 rounded-lg p-3 text-xs" style={{ background: "var(--surface-raised)", border: "1px solid var(--border)" }}>
              <div className="flex items-center gap-2 font-semibold" style={{ color: brokerReadiness?.ready ? "var(--positive)" : "var(--warning)" }}>
                {brokerReadiness?.ready ? <CheckCircle size={14} /> : <AlertTriangle size={14} />}
                {brokerReadiness?.ready ? "Tradier is ready" : "Tradier is not ready yet"}
              </div>
              <p className="mt-1" style={{ color: "var(--ink-muted)" }}>
                The server will not activate Tradier until account, order, position, clock, and fresh-price checks all pass.
              </p>
              {brokerReadiness && !brokerReadiness.ready && (
                <ul className="mt-2 pl-4 list-disc" style={{ color: "var(--ink-muted)" }}>
                  {Object.entries(brokerReadiness.checks).filter(([, check]) => !check.passed).map(([name, check]) => (
                    <li key={name}>{name.replaceAll("_", " ")}: {check.detail}</li>
                  ))}
                </ul>
              )}
              <button className="btn btn-ghost btn-sm mt-2" onClick={() => refreshBrokerReadiness()} disabled={checkingBroker}>
                {checkingBroker ? "Checking…" : "Check again"}
              </button>
            </div>
          )}
        </div>
        {(form as any).paper_trading === false && (
          <p className="text-xs mt-2" style={{ color: "#f87171" }}>
            ⚠️ Live mode places real orders with real money. Ensure your selected broker's live credentials are configured.
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

      {/* Keep the short display card in the same stack, not a mostly empty column. */}
      <div className="card p-4">
        <h3 className="text-sm font-semibold mb-3" style={{ color: "var(--ink)" }}>Display</h3>
        <div className="flex flex-col gap-2">
          <label className="text-sm" style={{ color: "var(--ink)" }}>
            Timezone
            <span className="block text-xs mt-0.5" style={{ color: "var(--ink-muted)" }}>
              Used for chart timestamps and log times
            </span>
          </label>
          <select
            className="select w-full min-w-0"
            value={form.display_timezone ?? "America/New_York"}
            onChange={(e) => set("display_timezone", e.target.value)}
          >
            {TIMEZONES.map((tz) => (
              <option key={tz.value} value={tz.value}>{tz.label}</option>
            ))}
          </select>
        </div>
      </div>
      </section>
      <section className="settings-control-stack" aria-label="Trade rules and scanner">
      {/* Plain-language controls that directly change order size or stop trading. */}
      <div className="card p-4">
        <div className="flex items-center justify-between gap-2"><h3 className="text-sm font-semibold" style={{ color: "var(--ink)" }}>Trade limits</h3><span className="badge badge-green">USED ON EVERY ORDER</span></div>

        <div className="flex flex-col gap-3">
          <div className="flex items-center justify-between gap-4 pt-2">
            <label className="text-sm" style={{ color: "var(--ink)" }}>
              Trade risk budget
              <span className="block text-xs mt-0.5" style={{ color: "var(--ink-muted)" }}>{form.risk_auto ? `Automatic: ${form.risk_pct}% for the current balance` : `Your choice: ${form.risk_pct}% of the account per trade`}</span>
            </label>
            <button type="button" className={`btn ${form.risk_auto ? "btn-primary" : "btn-ghost"}`} onClick={() => set("risk_auto", !form.risk_auto)}>{form.risk_auto ? "Automatic" : "Manual"}</button>
          </div>

          {!form.risk_auto && <div className="flex items-center justify-between gap-4 pl-3">
            <label htmlFor="trade-risk-percent" className="text-xs" style={{ color: "var(--ink-muted)" }}>Risk per trade</label><div className="flex items-center gap-1"><input
              id="trade-risk-percent"
              type="number"
              step="0.1"
              min="0.1"
              max="100"
              value={form.risk_pct}
              disabled={form.risk_auto}
              onChange={(e) => {
                set("risk_pct", parseFloat(e.target.value));
              }}
              className="input w-20"
            /><span className="text-sm">%</span></div>
          </div>}
          <p className="text-xs" style={{ color: "var(--ink-muted)" }}>For strategies without a premium stop, the full option cost uses this budget. This is a sizing limit, not an automatic exit.</p>

          <div className="flex items-center justify-between gap-4">
            <label className="text-sm" style={{ color: "var(--ink)" }}>
              Maximum open trades
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
            <label className="text-sm" style={{ color: "var(--ink)" }}>Maximum contract cost<span className="block text-xs mt-0.5" style={{ color: "var(--ink-muted)" }}>Percent of account balance</span></label>
            <div className="flex items-center gap-1"><input type="number" step="1" min="5" max="100" value={form.max_position_dollars_pct ?? 15} onChange={(e) => set("max_position_dollars_pct", parseFloat(e.target.value))} className="input w-20" /><span className="text-sm">%</span></div>
          </div>
          <div className="flex items-center justify-between gap-4">
            <label className="text-sm" style={{ color: "var(--ink)" }}>Daily loss stop<span className="block text-xs mt-0.5" style={{ color: "var(--ink-muted)" }}>Pauses new entries for the day</span></label>
            <div className="flex items-center gap-1"><input type="number" step="1" min="3" max="30" value={form.daily_loss_hard_cap_pct ?? 10} onChange={(e) => set("daily_loss_hard_cap_pct", parseFloat(e.target.value))} className="input w-20" /><span className="text-sm">%</span></div>
          </div>
          <details className="pt-2" style={{ borderTop: "1px solid var(--border)" }}>
            <summary className="text-xs cursor-pointer font-medium">More trade limits</summary>
            <div className="mt-3 flex flex-col gap-3">
              <div className="flex items-center justify-between gap-4"><label className="text-sm">Minimum reward compared with risk<span className="block text-xs" style={{ color: "var(--ink-muted)" }}>Skips a setup when its planned reward is too small.</span></label><select className="select w-40" value={form.rr_ratio_mode} onChange={(e) => set("rr_ratio_mode", e.target.value)}><option value="auto">Automatic</option><option value="small_account">1.2 to 1</option><option value="professional">1.6 to 1</option></select></div>
              <Toggle label="Use profit to increase future trade size" checked={form.growth_mode} onChange={(v) => set("growth_mode", v)} />
              <Toggle label="Allow a new opposite-direction trade after a breakdown" checked={form.flip_trading_enabled} onChange={(v) => set("flip_trading_enabled", v)} />
            </div>
          </details>
        </div>
      </div>

      {/* Detailed entry/exit behavior stays available without overwhelming the main page. */}
      <details className="card p-4">
        <summary className="text-sm font-semibold cursor-pointer" style={{ color: "var(--ink)" }}>Entry and exit controls</summary>
        <p className="text-xs mt-1" style={{ color: "var(--ink-muted)" }}>Advanced controls. Current values stay active while this is closed.</p>
        <div className="flex flex-col gap-5 mt-4">
        <section className="rounded-lg p-3" style={{ background: "var(--surface-raised)", border: "1px solid var(--border)" }}>
        <h3 className="text-sm font-semibold mb-3" style={{ color: "var(--ink)" }}>Contract filters</h3>
        <p className="text-xs mb-3" style={{ color: "var(--ink-muted)" }}>
          Legacy profit-target and premium-stop defaults do not override a reviewed strategy&apos;s exit rule.
        </p>
        <div className="flex flex-col gap-3">
          <div className="flex items-center justify-between gap-4">
            <label className="text-sm" style={{ color: "var(--ink)" }}>
              Legacy profit target (% gain)
              <span className="block text-xs mt-0.5" style={{ color: "var(--ink-muted)" }}>
                Used by the legacy partial-exit engine only, not reviewed strategy exits.
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
              Legacy premium stop (% loss)
              <span className="block text-xs mt-0.5" style={{ color: "var(--ink-muted)" }}>
                Used by legacy exit engines only. Not a guaranteed loss limit or a reviewed-strategy exit.
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
        </div>
      </section>

      <StrategyExitNotice />

      {/* Entry confirmation — controls whether a trade gets taken at all */}
      <section className="rounded-lg p-3" style={{ background: "var(--surface-raised)", border: "1px solid var(--border)" }}>
        <h3 className="text-sm font-semibold mb-1" style={{ color: "var(--ink)" }}>1-hour entry check</h3>
        <p className="text-xs mb-3" style={{ color: "var(--ink-muted)" }}>
          Checks the 1-hour trend before an entry. It never closes a position.
        </p>
        <Toggle
          label="MTF confirmation gate (live 1Hour bias check)"
          checked={form.mtf_confirmation_enabled ?? true}
          onChange={(v) => set("mtf_confirmation_enabled", v)}
        />
        <p className="text-xs" style={{ color: "var(--ink-muted)" }}>
          Uses the current API view and is not part of historical backtests.
        </p>
        <Toggle
          label="Opportunity cohort (observation-only lower-confidence experiments)"
          checked={form.opportunity_tier_enabled ?? false}
          onChange={(v) => set("opportunity_tier_enabled", v)}
        />
        <p className="text-xs" style={{ color: "var(--ink-muted)" }}>
          Off by default: the latest locked-holdout panel added too many trades
          and hurt results. When off, candidates are still tagged in Strategy
          Health so you can learn from them without letting them enter.
        </p>
      </section>
        </div>
      </details>

      {/* Watchlist */}
      <div className="card p-4">
        <h3 className="text-sm font-semibold mb-1" style={{ color: "var(--ink)" }}>Always include</h3>
        <p className="text-xs mb-3" style={{ color: "var(--ink-muted)" }}>The scanner checks these tickers even when they are not in today's top results.</p>
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
        <p className="text-xs mt-1" style={{ color: "var(--ink-muted)" }}>Separate tickers with commas.</p>
      </div>
      </section>
      </div>

      {/* API Credentials — two independent panels, see the comment above
          AlpacaCredentialsPanel for why they're structurally separate now */}
      <section className="flex flex-col gap-3" aria-label="API credentials">
      <p className="text-xs font-semibold px-1" style={{ color: "var(--ink-muted)" }}>
        API Credentials — each saves independently
      </p>
      <div className="settings-paired-grid">
        <AlpacaCredentialsPanel />
        <TradierCredentialsPanel provider={actualBrokerProvider} paper={actualAccountMode === "paper"} />
      </div>
      <p className="text-xs px-1" style={{ color: "var(--ink-muted)" }}>
        Keys are encrypted at rest (AES-128 / Fernet). Never stored in plain text.
      </p>
      </section>

      </div>
      <div hidden={activeTab !== "strategies"} id="settings-panel-strategies" role="tabpanel" aria-labelledby="settings-tab-strategies" className={activeTab === "strategies" ? "flex flex-col gap-4" : "hidden"}>
      {/* Strategies */}
      <section>
        <h3 className="text-base font-semibold" style={{ color: "var(--ink)" }}>Can place orders</h3>
        <p className="text-xs mb-3" style={{ color: "var(--ink-muted)" }}>
          On means the strategy may place {actualAccountMode} orders on the tickers listed under “Trades.” Research continues on all other collected tickers.
        </p>
        <div className="settings-card-grid">{(strategyCatalog?.strategies ?? []).filter(strategy => !strategy.observation_only).map(strategyControl)}</div>
        <div className="mt-3 text-xs" style={{ color: "var(--ink-muted)" }}>
          New ticker matches observe automatically without placing orders. If one passes review, every user receives a prompt and decides whether to turn it on for their own account.
        </div>
        {(strategyHistory?.changes.length ?? 0) > 0 && (
          <details className="mt-3 text-xs" style={{ color: "var(--ink-muted)" }}>
            <summary className="cursor-pointer font-medium" style={{ color: "var(--ink)" }}>Recent strategy switch history</summary>
            <div className="mt-2 flex flex-col gap-1">
              {strategyHistory!.changes.map((change, index) => (
                <div key={`${change.changed_at}-${change.strategy_id}-${index}`}>
                  {new Date(change.changed_at).toLocaleString()} · {change.strategy_id} · {change.previous_enabled ? "ON" : "OFF"} → {change.new_enabled ? "ON" : "OFF"}
                </div>
              ))}
            </div>
          </details>
        )}
      </section>

      <section>
        <h3 className="text-base font-semibold" style={{ color: "var(--ink)" }}>Research only</h3>
        <p className="text-xs mb-3" style={{ color: "var(--ink-muted)" }}>
          On means keep testing every collected ticker. {strategyResearch?.collection_started_on ? `Data collected since ${evidenceDate(strategyResearch.collection_started_on)} · ${strategyResearch.collected_market_days} market days · ${strategyResearch.ticker_count} tickers.` : "No market data collected yet."} New matches need 20 non-overlapping completed tests and passing profit checks—not a minimum number of days.
        </p>
        <div className="settings-card-grid">
        {(strategyCatalog?.strategies ?? []).filter(strategy => strategy.observation_only).map(strategyControl)}
        <TestedStrategies
          embedded
          researchIds={form.research_strategy_ids ?? []}
          onResearchIdsChange={ids => set("research_strategy_ids", ids)}
          researchMatrix={strategyResearch}
        />
        </div>
      </section>
      </div>

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
      {saveError && <p className="text-xs" style={{ color: "#f87171" }}>{saveError}</p>}
    </div>
  );
}
