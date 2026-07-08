/**
 * kchartIndicators.ts — Custom KLineChart indicators.
 * Registered globally (idempotent) before first chart init.
 */
import { registerIndicator } from "klinecharts";

let _done = false;

export function registerCustomIndicators() {
  if (_done) return;
  _done = true;

  // ── VWAP with ±1σ bands (intraday — resets each calendar day) ────────────
  registerIndicator({
    name:      "VWAP",
    shortName: "VWAP",
    series:    "price",
    figures: [
      { key: "vwap",   title: "VWAP", type: "line" },
      { key: "upper1", title: "+1σ",  type: "line" },
      { key: "lower1", title: "-1σ",  type: "line" },
    ],
    calc(dataList: any[]) {
      let cumTPV = 0, cumTPV2 = 0, cumVol = 0, day = "";
      return dataList.map((d: any) => {
        const dd = new Date(d.timestamp).toISOString().slice(0, 10);
        // Reset accumulators at start of each new trading day
        if (dd !== day) { cumTPV = 0; cumTPV2 = 0; cumVol = 0; day = dd; }
        const tp  = (d.high + d.low + d.close) / 3;
        const vol = d.volume ?? 0;
        cumTPV  += tp  * vol;
        cumTPV2 += tp  * tp * vol;
        cumVol  += vol;
        if (!cumVol) return { vwap: null, upper1: null, lower1: null };
        const vwap  = cumTPV / cumVol;
        const sigma = Math.sqrt(Math.max(0, (cumTPV2 / cumVol) - vwap * vwap));
        return { vwap, upper1: vwap + sigma, lower1: vwap - sigma };
      });
    },
  } as any);
}
