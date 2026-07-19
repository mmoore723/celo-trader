/**
 * chartOverlays.ts — everything drawn ON TOP of candles/volume: VWAP lines,
 * OR lines, position/simulation/replay price lines, shaded zone bands
 * (OR box, P&L bracket, premium/discount, killzones), and every marker type
 * (trades, swing structure + BOS/CHoCH, bot annotations, execution grade).
 *
 * Kept separate from chartCore.ts so the engine (series lifecycle) and the
 * teaching content (what gets drawn and why) aren't tangled together.
 */
import { createSeriesMarkers, LineSeries, LineStyle } from "lightweight-charts";
import type { IChartApi, ISeriesApi, IPriceLine, Time } from "lightweight-charts";
import type { Bar, Trade, ChartAnnotation } from "../../lib/api";
import type { PositionLevels } from "./chartTypes";
import type { SimulationOverlay, ReplayTrade } from "../../lib/chart_types";
import type { ChartPalette } from "./palette";
import { premiumDiscountRange, killzoneRangesForBars } from "./zones";
import { ZoneBandManager, toEpochTime } from "./zoneBands";
import { buildAndApplyMarkers } from "./chartMarkers";

export interface OverlayInputs {
  bars: Bar[];
  trades: Trade[];
  annotations: ChartAnnotation[];
  showVwap: boolean;
  showSwings: boolean;
  showStructure: boolean;      // BOS/CHoCH labels
  showPremiumDiscount: boolean;
  showKillzones: boolean;
  showExecutionGrade: boolean;
  orHigh?: number;
  orLow?: number;
  positionLevels?: PositionLevels;
  simulationOverlay?: SimulationOverlay;
  replayTrade?: ReplayTrade;
}

/** Tracks price-line handles across renders so they can be cleared before redrawing. */
export class OverlayManager {
  private candle: ISeriesApi<"Candlestick">;
  private vwapLines: Record<"vwap" | "u1" | "l1" | "u2" | "l2", ISeriesApi<"Line"> | null> = { vwap: null, u1: null, l1: null, u2: null, l2: null };
  private priceLines: IPriceLine[] = [];
  private zoneMgr: ZoneBandManager;
  private palette: ChartPalette;
  private chart: IChartApi;

  constructor(chart: IChartApi, candle: ISeriesApi<"Candlestick">, palette: ChartPalette) {
    this.chart = chart;
    this.candle = candle;
    this.zoneMgr = new ZoneBandManager(chart);
    this.palette = palette;
  }

  /** VWAP + ±1σ/±2σ bands as plain lines (see chartOverlays.ts header — these
   * two edges both move every bar, so they stay lines rather than a shaded
   * fill; see zoneBands.ts for why). Created once, data updated per call. */
  setVwap(bars: Bar[], showVwap: boolean, showBands: boolean) {
    const P = this.palette;
    if (!showVwap) {
      for (const key of Object.keys(this.vwapLines) as (keyof typeof this.vwapLines)[]) {
        this.vwapLines[key]?.setData([]);
      }
      return;
    }
    const ensure = (key: keyof typeof this.vwapLines, color: string, width: 1 | 2, dashed: boolean) => {
      if (!this.vwapLines[key]) {
        this.vwapLines[key] = this.chart.addSeries(LineSeries, {
          color, lineWidth: width, lineStyle: dashed ? LineStyle.Dashed : LineStyle.Solid,
          priceLineVisible: false, crosshairMarkerVisible: false,
        }) as unknown as ISeriesApi<"Line">;
      }
      return this.vwapLines[key]!;
    };
    ensure("vwap", P.vwap, 2, false).setData(bars.filter((b) => b.vwap != null).map((b) => ({ time: toEpochTime(b.time), value: b.vwap! })));
    if (showBands) {
      ensure("u1", P.vwapBand1.slice(0, 7), 1, true).setData(bars.filter((b) => b.vwap_upper1 != null).map((b) => ({ time: toEpochTime(b.time), value: b.vwap_upper1! })));
      ensure("l1", P.vwapBand1.slice(0, 7), 1, true).setData(bars.filter((b) => b.vwap_lower1 != null).map((b) => ({ time: toEpochTime(b.time), value: b.vwap_lower1! })));
      ensure("u2", P.vwapBand2.slice(0, 7), 1, true).setData(bars.filter((b) => b.vwap_upper2 != null).map((b) => ({ time: toEpochTime(b.time), value: b.vwap_upper2! })));
      ensure("l2", P.vwapBand2.slice(0, 7), 1, true).setData(bars.filter((b) => b.vwap_lower2 != null).map((b) => ({ time: toEpochTime(b.time), value: b.vwap_lower2! })));
    } else {
      this.vwapLines.u1?.setData([]);
      this.vwapLines.l1?.setData([]);
      this.vwapLines.u2?.setData([]);
      this.vwapLines.l2?.setData([]);
    }
  }

  private clearPriceLines() {
    for (const pl of this.priceLines) { try { this.candle.removePriceLine(pl); } catch { /* gone */ } }
    this.priceLines = [];
  }

  apply(input: OverlayInputs) {
    const P = this.palette;
    this.clearPriceLines();
    const zoneSpecs: Parameters<ZoneBandManager["sync"]>[0] = [];

    if (input.bars.length === 0) { this.zoneMgr.sync([]); createSeriesMarkers(this.candle, []); return; }
    const firstT = toEpochTime(input.bars[0].time);
    const lastT = toEpochTime(input.bars[input.bars.length - 1].time);

    // ── Opening range: line + shaded box ────────────────────────────────────
    if (input.orHigh != null) this.priceLines.push(this.candle.createPriceLine({ price: input.orHigh, color: P.orHigh, lineWidth: 2, lineStyle: LineStyle.Solid, title: "OR Hi" }));
    if (input.orLow != null) this.priceLines.push(this.candle.createPriceLine({ price: input.orLow, color: P.orLow, lineWidth: 2, lineStyle: LineStyle.Solid, title: "OR Lo" }));
    if (input.orHigh != null && input.orLow != null) {
      zoneSpecs.push({ id: "or_zone", fromTime: firstT, toTime: lastT, low: input.orLow, high: input.orHigh, color: P.orHigh + "18" });
    }

    // ── Premium / discount split ─────────────────────────────────────────────
    if (input.showPremiumDiscount) {
      const range = premiumDiscountRange(input.bars);
      if (range) {
        zoneSpecs.push({ id: "premium", fromTime: firstT, toTime: lastT, low: range.mid, high: range.high, color: P.premium });
        zoneSpecs.push({ id: "discount", fromTime: firstT, toTime: lastT, low: range.low, high: range.mid, color: P.discount });
      }
    }

    // ── Killzones ─────────────────────────────────────────────────────────────
    if (input.showKillzones) {
      const kzs = killzoneRangesForBars(input.bars);
      const barLow = Math.min(...input.bars.map((b) => b.low));
      const barHigh = Math.max(...input.bars.map((b) => b.high));
      for (const kz of kzs) {
        zoneSpecs.push({ id: `kz_${kz.key}`, fromTime: (kz.start / 1000) as Time, toTime: (kz.end / 1000) as Time, low: barLow, high: barHigh, color: P.killzone });
      }
    }

    // ── Position bracket (live open trade) ──────────────────────────────────
    const pl = input.positionLevels;
    if (pl?.entry != null) {
      const entry = pl.entry;
      const defs: { key: "stop" | "target" | "trail"; color: string; label: string }[] = [
        { key: "stop", color: P.stop, label: "Stop" }, { key: "target", color: P.target, label: "Target" }, { key: "trail", color: P.trail, label: "Trail" },
      ];
      this.priceLines.push(this.candle.createPriceLine({ price: entry, color: P.entry, lineWidth: 2, title: `Entry $${entry.toFixed(2)}` }));
      for (const d of defs) {
        const price = pl[d.key];
        if (price != null && price > 0) this.priceLines.push(this.candle.createPriceLine({ price, color: d.color, lineWidth: 1, lineStyle: d.key === "trail" ? LineStyle.Dashed : LineStyle.Solid, title: `${d.label} $${price.toFixed(2)}` }));
      }
      if (pl.stop != null) zoneSpecs.push({ id: "pos_risk", fromTime: firstT, toTime: lastT, low: Math.min(entry, pl.stop), high: Math.max(entry, pl.stop), color: P.stop + "18" });
      if (pl.target != null) zoneSpecs.push({ id: "pos_reward", fromTime: firstT, toTime: lastT, low: Math.min(entry, pl.target), high: Math.max(entry, pl.target), color: P.target + "18" });
    }

    // ── Simulation overlay ────────────────────────────────────────────────────
    if (input.simulationOverlay) {
      const s = input.simulationOverlay;
      const isCall = s.direction === "calls";
      this.priceLines.push(this.candle.createPriceLine({ price: s.entryTrigger, color: isCall ? P.up : P.down, lineWidth: 2, title: "Entry Trigger" }));
      this.priceLines.push(this.candle.createPriceLine({ price: s.stage1Px, color: P.target, lineWidth: 1, lineStyle: LineStyle.Dashed, title: "Stage 1" }));
      this.priceLines.push(this.candle.createPriceLine({ price: s.stopPx, color: P.stop, lineWidth: 1, lineStyle: LineStyle.Dashed, title: "Stop" }));
      zoneSpecs.push({ id: "sim_reward", fromTime: firstT, toTime: lastT, low: Math.min(s.entryTrigger, s.stage1Px), high: Math.max(s.entryTrigger, s.stage1Px), color: P.target + "18" });
      zoneSpecs.push({ id: "sim_risk", fromTime: firstT, toTime: lastT, low: Math.min(s.entryTrigger, s.stopPx), high: Math.max(s.entryTrigger, s.stopPx), color: P.stop + "18" });
    }

    // ── Replay MFE/MAE ────────────────────────────────────────────────────────
    if (input.replayTrade) {
      const rt = input.replayTrade;
      if (rt.peak_option_px != null) this.priceLines.push(this.candle.createPriceLine({ price: rt.peak_option_px, color: "#a78bfa", lineWidth: 1, lineStyle: LineStyle.Dotted, title: `MFE ${rt.peak_option_px.toFixed(2)}` }));
      if (rt.mae_option_px != null) this.priceLines.push(this.candle.createPriceLine({ price: rt.mae_option_px, color: "#f87171", lineWidth: 1, lineStyle: LineStyle.Dotted, title: `MAE ${rt.mae_option_px.toFixed(2)}` }));
    }

    // ── Bot annotations (hline / zone) ───────────────────────────────────────
    for (const ann of input.annotations) {
      if (ann.type === "hline" && ann.price != null) this.priceLines.push(this.candle.createPriceLine({ price: ann.price, color: ann.color, lineWidth: 1, lineStyle: LineStyle.Dashed, title: ann.label }));
      else if (ann.type === "zone" && ann.price_low != null && ann.price_high != null) zoneSpecs.push({ id: `ann_${ann.id}`, fromTime: firstT, toTime: lastT, low: ann.price_low, high: ann.price_high, color: ann.color + "22" });
    }

    this.zoneMgr.sync(zoneSpecs);
    buildAndApplyMarkers(this.candle, input, P);
  }

  destroy() {
    this.clearPriceLines();
    this.zoneMgr.destroy();
    for (const key of Object.keys(this.vwapLines) as (keyof typeof this.vwapLines)[]) {
      const s = this.vwapLines[key];
      if (s) { try { this.chart.removeSeries(s); } catch { /* chart already disposed */ } }
      this.vwapLines[key] = null;
    }
  }
}
