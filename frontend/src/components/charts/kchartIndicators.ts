/**
 * kchartIndicators.ts — Custom KLineChart v9 indicators + overlays.
 * All registrations are idempotent (run once at module load).
 */
import { registerIndicator, registerOverlay } from "klinecharts";

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
        if (dd !== day) { cumTPV = 0; cumTPV2 = 0; cumVol = 0; day = dd; }
        const tp  = (d.high + d.low + d.close) / 3;
        const vol = d.volume ?? 0;
        cumTPV  += tp * vol;
        cumTPV2 += tp * tp * vol;
        cumVol  += vol;
        if (!cumVol) return { vwap: null, upper1: null, lower1: null };
        const vwap  = cumTPV / cumVol;
        const sigma = Math.sqrt(Math.max(0, (cumTPV2 / cumVol) - vwap * vwap));
        return { vwap, upper1: vwap + sigma, lower1: vwap - sigma };
      });
    },
  } as any);

  // ── Buy marker — upward triangle drawn below the bar ─────────────────────
  registerOverlay({
    name: "buyMarker",
    totalStep: 1,
    needDefaultPointFigure: false,
    needDefaultXAxisFigure: false,
    needDefaultYAxisFigure: false,
    createPointFigures: ({ coordinates, overlay }: any) => {
      if (!coordinates[0]) return [];
      const { x, y } = coordinates[0];
      const size = 8;
      const label = (overlay.extendData as string) ?? "B";
      return [
        // Triangle pointing up, drawn BELOW the entry price
        {
          type: "polygon",
          attrs: {
            coordinates: [
              { x, y: y + 4 },
              { x: x - size, y: y + 4 + size * 1.6 },
              { x: x + size, y: y + 4 + size * 1.6 },
            ],
          },
          styles: { style: "fill", color: "#26a69a" },
        },
        // Label text
        {
          type: "text",
          ignoreEvent: true,
          attrs: { x, y: y + 4 + size * 1.6 + 10, text: label, align: "center", baseline: "top" },
          styles: { color: "#26a69a", size: 9, family: "monospace", style: "fill" },
        },
      ];
    },
  } as any);

  // ── Sell marker — downward triangle drawn above the bar ───────────────────
  registerOverlay({
    name: "sellMarker",
    totalStep: 1,
    needDefaultPointFigure: false,
    needDefaultXAxisFigure: false,
    needDefaultYAxisFigure: false,
    createPointFigures: ({ coordinates, overlay }: any) => {
      if (!coordinates[0]) return [];
      const { x, y } = coordinates[0];
      const size = 8;
      const label = (overlay.extendData as string) ?? "S";
      return [
        // Triangle pointing down, drawn ABOVE the bar
        {
          type: "polygon",
          attrs: {
            coordinates: [
              { x, y: y - 4 },
              { x: x - size, y: y - 4 - size * 1.6 },
              { x: x + size, y: y - 4 - size * 1.6 },
            ],
          },
          styles: { style: "fill", color: "#ef5350" },
        },
        {
          type: "text",
          ignoreEvent: true,
          attrs: { x, y: y - 4 - size * 1.6 - 2, text: label, align: "center", baseline: "bottom" },
          styles: { color: "#ef5350", size: 9, family: "monospace", style: "fill" },
        },
      ];
    },
  } as any);

  // ── Exit marker — small X circle ─────────────────────────────────────────
  registerOverlay({
    name: "exitMarker",
    totalStep: 1,
    needDefaultPointFigure: false,
    needDefaultXAxisFigure: false,
    needDefaultYAxisFigure: false,
    createPointFigures: ({ coordinates }: any) => {
      if (!coordinates[0]) return [];
      const { x, y } = coordinates[0];
      return [
        {
          type: "circle",
          attrs: { x, y, r: 5 },
          styles: { style: "stroke_fill", color: "#f59e0b44", borderColor: "#f59e0b", borderSize: 2 },
        },
      ];
    },
  } as any);
}
