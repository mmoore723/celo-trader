/**
 * Settings.tsx — Bot configuration form.
 */
import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Save } from "lucide-react";
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
  risk_pct: 1.0,
  growth_mode: false,
  flip_trading_enabled: true,
  max_concurrent_positions: 1,
  rr_ratio_mode: "dynamic",
  watchlist: ["SPY"],
  orb_enabled: true,
  vwap_pullback_enabled: true,
  fvg_enabled: true,
  bos_mss_enabled: true,
  chan_break_enabled: true,
  mid_brk_enabled: true,
  trend_cont_enabled: true,
};

export function Settings() {
  const [form, setForm] = useState<AppSettings>(DEFAULT);
  const [saved, setSaved] = useState(false);
  const qc = useQueryClient();

  const { data } = useQuery({
    queryKey: ["settings"],
    queryFn: api.settings.get,
  });

  useEffect(() => {
    if (data) setForm(data);
  }, [data]);

  function set<K extends keyof AppSettings>(key: K, val: AppSettings[K]) {
    setForm((f) => ({ ...f, [key]: val }));
    setSaved(false);
  }

  async function save() {
    await api.settings.save(form);
    qc.invalidateQueries({ queryKey: ["settings"] });
    setSaved(true);
    setTimeout(() => setSaved(false), 2500);
  }

  return (
    <div className="p-4 max-w-2xl flex flex-col gap-4">
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
              onChange={(e) => set("risk_pct", parseFloat(e.target.value))}
              className="input w-24"
            />
          </div>

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
              <option value="dynamic">Dynamic</option>
              <option value="fixed_2_1">Fixed 2:1</option>
              <option value="fixed_3_1">Fixed 3:1</option>
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
        <Toggle label="BOS / MSS — Break of Structure (all session)" checked={form.bos_mss_enabled}
                onChange={(v) => set("bos_mss_enabled", v)} />
        <Toggle label="Channel Breakout (9:45 AM – 3:45 PM)" checked={form.chan_break_enabled}
                onChange={(v) => set("chan_break_enabled", v)} />
        <Toggle label="Mid-Day Breakdown / MID_BRK (10:30 AM – 1:00 PM)" checked={form.mid_brk_enabled}
                onChange={(v) => set("mid_brk_enabled", v)} />
        <Toggle label="Trend Continuation / TREND_CONT (9:45 AM – 2:30 PM)" checked={form.trend_cont_enabled}
                onChange={(v) => set("trend_cont_enabled", v)} />
      </div>

      {/* Watchlist */}
      <div className="card p-4">
        <h3 className="text-sm font-semibold mb-3" style={{ color: "var(--ink)" }}>Watchlist</h3>
        <textarea
          className="input w-full font-mono text-sm"
          rows={3}
          value={form.watchlist.join(", ")}
          onChange={(e) =>
            set("watchlist", e.target.value.split(",").map((t) => t.trim().toUpperCase()).filter(Boolean))
          }
          placeholder="SPY, QQQ, NVDA…"
        />
        <p className="text-xs mt-1" style={{ color: "var(--ink-muted)" }}>
          Comma-separated tickers. Scanner may override this during market hours.
        </p>
      </div>

      {/* Save */}
      <button
        className={`btn w-full justify-center ${saved ? "btn-ghost" : "btn-primary"}`}
        onClick={save}
      >
        <Save size={14} />
        {saved ? "Saved!" : "Save Settings"}
      </button>
    </div>
  );
}
