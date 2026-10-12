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
import type { IChartApi, ISeriesApi, ISeriesMarkersPluginApi, IPriceLine, Time } from "lightweight-charts";
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
  positionLevelsOnCandleScale?: boolean;
  simulationOverlay?: SimulationOverlay;
  replayTrade?: ReplayTrade;
}

/** Tracks price-line handles across renders so they can be cleared before redrawing. */
export class OverlayManager {
  private candle: ISeriesApi<"Candlestick">;
  private vwapLines: Record<"vwap" | "u1" | "l1" | "u2" | "l2", ISeriesApi<"Line"> | null> = { vwap: null, u1: null, l1: null, u2: null, l2: null };
  // { series, line } pairs so clearPriceLines() can call removePriceLine on
  // whichever series a given line actually belongs to.
  private priceLines: { series: ISeriesApi<"Candlestick"> | ISeriesApi<"Line">; line: IPriceLine }[] = [];
  // FIX 2026-07-31: real bug — option premium levels (position entry/stop/
  // target/trail, and replay MFE/MAE) used to be drawn with
  // candle.createPriceLine(), sharing the STOCK candle's price axis. A
  // $4.85 option premium on an axis scaled to AMZN's $260-360 stock price
  // collapses to a meaningless sliver at the bottom of the chart. This
  // hidden line series has its own independent price scale ("trade_levels")
  // so those dollar levels get correct relative spacing to each other
  // without cluttering the stock axis. The series itself is invisible
  // (visible:false) — it exists only so createPriceLine() has a scale to
  // anchor to; lightweight-charts includes price lines in a series'
  // autoscale, so seeding it with the levels' own range is enough.
  private tradeLevelAnchor: ISeriesApi<"Line"> | null = null;
  // Stock-price reference lines stay on the stock scale but are excluded
  // from autoscale. A stale OR or annotation can remain visible when it is
  // relevant without crushing the candles into a narrow strip.
  private referenceAnchor: ISeriesApi<"Line"> | null = null;
  private zoneMgr: ZoneBandManager;
  private palette: ChartPalette;
  private chart: IChartApi;
  // Single reused marker-primitive handle — see chartMarkers.ts header comment
  // for why this must be reused (via .setMarkers()) rather than recreated
  // on every apply() call.
  private markersPrimitive: ISeriesMarkersPluginApi<Time> | null = null;

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
    for (const { series, line } of this.priceLines) { try { series.removePriceLine(line); } catch { /* gone */ } }
    this.priceLines = [];
  }

  /** Lazily creates the hidden trade-level anchor series (own price scale). */
  private ensureTradeLevelAnchor(): ISeriesApi<"Line"> {
    if (!this.tradeLevelAnchor) {
      this.tradeLevelAnchor = this.chart.addSeries(LineSeries, {
        priceScaleId: "trade_levels",
        visible: false,
        lastValueVisible: false,
        priceLineVisible: false,
        crosshairMarkerVisible: false,
      }) as unknown as ISeriesApi<"Line">;
      this.chart.priceScale("trade_levels").applyOptions({ visible: false });
    }
    return this.tradeLevelAnchor;
  }

  private ensureReferenceAnchor(firstT: Time, lastT: Time, price: number): ISeriesApi<"Line"> {
    if (!this.referenceAnchor) {
      this.referenceAnchor = this.chart.addSeries(LineSeries, {
        color: "transparent",
        lineWidth: 1,
        lastValueVisible: false,
        priceLineVisible: false,
        crosshairMarkerVisible: false,
        autoscaleInfoProvider: () => null,
      }) as unknown as ISeriesApi<"Line">;
    }
    this.referenceAnchor.setData([{ time: firstT, value: price }, { time: lastT, value: price }]);
    return this.referenceAnchor;
  }

  apply(input: OverlayInputs) {
    const P = this.palette;
    this.clearPriceLines();
    const zoneSpecs: Parameters<ZoneBandManager["sync"]>[0] = [];

    if (input.bars.length === 0) {
      this.zoneMgr.sync([]);
      if (this.markersPrimitive) this.markersPrimitive.setMarkers([]);
      else this.markersPrimitive = createSeriesMarkers(this.candle, []);
      return;
    }
    const firstT = toEpochTime(input.bars[0].time);
    const lastT = toEpochTime(input.bars[input.bars.length - 1].time);
    const referenceAnchor = this.ensureReferenceAnchor(firstT, lastT, input.bars[input.bars.length - 1].close);

    // ── Opening range: line + shaded box ────────────────────────────────────
    // FIX 2026-07-31: the shaded OR box used to span fromTime=firstT — the
    // very first loaded bar, which on a multi-day chart is DAYS before the
    // range even formed. The backend only ever returns TODAY's OR (single
    // Hi/Lo pair, no history), so a box stretching back through yesterday's
    // session was never meaningful — real complaint: "it looks like a
    // static line for the full session... the bot is calculating different
    // ORB times," i.e. the box didn't visually track when today's range
    // actually formed. Bound it to today only: from market open (9:30 ET,
    // taken from the LAST loaded bar's calendar day, since that's the
    // session currently on screen) through the most recent bar. The two
    // thin reference lines below stay full-chart-width — lightweight-charts'
    // createPriceLine has no time-bound option — but the shaded box is what
    // visually dominated the "stretches across everything" complaint.
    const lastBarDate = new Date(input.bars[input.bars.length - 1].time);
    const todayOrStart = toEpochTime(
      new Date(lastBarDate.getFullYear(), lastBarDate.getMonth(), lastBarDate.getDate(), 9, 30, 0, 0).toISOString(),
    );
    const orZoneFrom = (todayOrStart as number) > (firstT as number) ? todayOrStart : firstT;

    if (input.orHigh != null) this.priceLines.push({ series: referenceAnchor, line: referenceAnchor.createPriceLine({ price: input.orHigh, color: P.orHigh, lineWidth: 2, lineStyle: LineStyle.Solid, title: "OR Hi" }) });
    if (input.orLow != null) this.priceLines.push({ series: referenceAnchor, line: referenceAnchor.createPriceLine({ price: input.orLow, color: P.orLow, lineWidth: 2, lineStyle: LineStyle.Solid, title: "OR Lo" }) });
    if (input.orHigh != null && input.orLow != null) {
      zoneSpecs.push({ id: "or_zone", fromTime: orZoneFrom, toTime: lastT, low: input.orLow, high: input.orHigh, color: P.orHigh + "18" });
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
    // On an underlying chart, option entry/stop/target values must stay on a
    // separate hidden scale. On the exact option-contract chart those values
    // share the candle's units, so draw them on the candle scale but use the
    // non-autoscaling reference series: distant targets/stops remain overlays
    // and never crush real candles into tiny dashes.
    // FIX 2026-07-31: entry/stop/target/trail are OPTION premium dollars
    // (e.g. $4.85), not stock price — drawn on `candle` they collapsed to a
    // sliver at the bottom of AMZN's $260-360 axis. Now anchored to their
    // own hidden scale (see ensureTradeLevelAnchor) so they're correctly
    // spaced relative to each other. Option-premium risk/reward shading is
    // deliberately not drawn on the underlying chart: a $4 option has no
    // valid coordinate on a $700 stock-price axis. The position card still
    // presents the entry, stop, target, and live P&L.
    const pl = input.positionLevels;
    if (pl?.entry != null) {
      const entry = pl.entry;
      const anchor = input.positionLevelsOnCandleScale
        ? referenceAnchor
        : this.ensureTradeLevelAnchor();
      const defs: { key: "stop" | "target" | "trail"; color: string; label: string }[] = [
        { key: "stop", color: P.stop, label: "Stop" }, { key: "target", color: P.target, label: "Target" }, { key: "trail", color: P.trail, label: "Trail" },
      ];
      if (!input.positionLevelsOnCandleScale) {
        // Seed the separate option-level scale. The exact-contract path uses
        // referenceAnchor, which already follows the candle scale.
        anchor.setData([{ time: firstT, value: entry }, { time: lastT, value: entry }]);
      } else {
        // A regular candle chart must be scaled by the traded prices, not by
        // a far-away reference target or stop. Clamp the colored position
        // zones to the actual visible candle range. The full target/stop
        // values remain in the position HUD; an in-range level still gets a
        // native chart line below.
        const candleLow = Math.min(...input.bars.map((bar) => bar.low));
        const candleHigh = Math.max(...input.bars.map((bar) => bar.high));
        if (pl.target != null && pl.target > entry && candleHigh > entry) zoneSpecs.push({
          id: "position_reward", fromTime: firstT, toTime: lastT,
          low: entry, high: Math.min(pl.target, candleHigh), color: P.target + "18",
        });
        if (pl.stop != null && pl.stop > 0 && pl.stop < entry && candleLow < entry) zoneSpecs.push({
          id: "position_risk", fromTime: firstT, toTime: lastT,
          low: Math.max(pl.stop, candleLow), high: entry, color: P.stop + "18",
        });
      }
      this.priceLines.push({ series: anchor, line: anchor.createPriceLine({ price: entry, color: P.entry, lineWidth: 2, title: `Entry $${entry.toFixed(2)}` }) });
      for (const d of defs) {
        const price = pl[d.key];
        const inVisibleCandleRange = !input.positionLevelsOnCandleScale
          || (price != null
            && price >= Math.min(...input.bars.map((bar) => bar.low))
            && price <= Math.max(...input.bars.map((bar) => bar.high)));
        if (price != null && price > 0 && inVisibleCandleRange) this.priceLines.push({ series: anchor, line: anchor.createPriceLine({ price, color: d.color, lineWidth: 1, lineStyle: d.key === "trail" ? LineStyle.Dashed : LineStyle.Solid, title: `${d.label} $${price.toFixed(2)}` }) });
      }
    } else if (this.tradeLevelAnchor) {
      this.tradeLevelAnchor.setData([]);
    }

    // ── Simulation overlay ────────────────────────────────────────────────────
    if (input.simulationOverlay) {
      const s = input.simulationOverlay;
      const isCall = s.direction === "calls";
      this.priceLines.push({ series: referenceAnchor, line: referenceAnchor.createPriceLine({ price: s.entryTrigger, color: isCall ? P.up : P.down, lineWidth: 2, title: "Entry Trigger" }) });
      this.priceLines.push({ series: referenceAnchor, line: referenceAnchor.createPriceLine({ price: s.stage1Px, color: P.target, lineWidth: 1, lineStyle: LineStyle.Dashed, title: "Stage 1" }) });
      this.priceLines.push({ series: referenceAnchor, line: referenceAnchor.createPriceLine({ price: s.stopPx, color: P.stop, lineWidth: 1, lineStyle: LineStyle.Dashed, title: "Stop" }) });
      zoneSpecs.push({ id: "sim_reward", fromTime: firstT, toTime: lastT, low: Math.min(s.entryTrigger, s.stage1Px), high: Math.max(s.entryTrigger, s.stage1Px), color: P.target + "18" });
      zoneSpecs.push({ id: "sim_risk", fromTime: firstT, toTime: lastT, low: Math.min(s.entryTrigger, s.stopPx), high: Math.max(s.entryTrigger, s.stopPx), color: P.stop + "18" });
    }

    // ── Replay MFE/MAE ────────────────────────────────────────────────────────
    // Same unit mismatch as the position bracket above — these are option
    // prices too (see ReplayTrade's peak_option_px/mae_option_px comments).
    // Only create the anchor here if the position bracket above didn't
    // already (a replay can run with no live position open).
    if (input.replayTrade) {
      const rt = input.replayTrade;
      if (rt.peak_option_px != null || rt.mae_option_px != null) {
        const anchor = this.ensureTradeLevelAnchor();
        if (!pl?.entry) {
          const seed = rt.peak_option_px ?? rt.mae_option_px!;
          anchor.setData([{ time: firstT, value: seed }, { time: lastT, value: seed }]);
        }
        if (rt.peak_option_px != null) this.priceLines.push({ series: anchor, line: anchor.createPriceLine({ price: rt.peak_option_px, color: "#a78bfa", lineWidth: 1, lineStyle: LineStyle.Dotted, title: `MFE ${rt.peak_option_px.toFixed(2)}` }) });
        if (rt.mae_option_px != null) this.priceLines.push({ series: anchor, line: anchor.createPriceLine({ price: rt.mae_option_px, color: "#f87171", lineWidth: 1, lineStyle: LineStyle.Dotted, title: `MAE ${rt.mae_option_px.toFixed(2)}` }) });
      }
    }

    // ── Bot annotations (hline / zone) ───────────────────────────────────────
    for (const ann of input.annotations) {
      if (ann.type === "hline" && ann.price != null) this.priceLines.push({ series: referenceAnchor, line: referenceAnchor.createPriceLine({ price: ann.price, color: ann.color, lineWidth: 1, lineStyle: LineStyle.Dashed, title: ann.label }) });
      else if (ann.type === "zone" && ann.price_low != null && ann.price_high != null) {
        const start = toEpochTime(ann.ts);
        const finish = ann.end_ts ? toEpochTime(ann.end_ts) : lastT;
        const from = Math.max(Number(firstT), Number(start));
        const to = Math.min(Number(lastT), Number(finish));
        if (Number.isFinite(from) && Number.isFinite(to) && to > from)
          zoneSpecs.push({ id: `ann_${ann.id}`, fromTime: from as Time, toTime: to as Time, low: ann.price_low, high: ann.price_high, color: ann.color + "22" });
      }
    }

    this.zoneMgr.sync(zoneSpecs);
    this.markersPrimitive = buildAndApplyMarkers(this.candle, input, P, this.markersPrimitive);
  }

  destroy() {
    this.clearPriceLines();
    this.zoneMgr.destroy();
    if (this.markersPrimitive) {
      try { this.markersPrimitive.detach(); } catch { /* series/chart already disposed */ }
      this.markersPrimitive = null;
    }
    for (const key of Object.keys(this.vwapLines) as (keyof typeof this.vwapLines)[]) {
      const s = this.vwapLines[key];
      if (s) { try { this.chart.removeSeries(s); } catch { /* chart already disposed */ } }
      this.vwapLines[key] = null;
    }
    if (this.tradeLevelAnchor) {
      try { this.chart.removeSeries(this.tradeLevelAnchor); } catch { /* chart already disposed */ }
      this.tradeLevelAnchor = null;
    }
    if (this.referenceAnchor) {
      try { this.chart.removeSeries(this.referenceAnchor); } catch { /* chart already disposed */ }
      this.referenceAnchor = null;
    }
  }
}
