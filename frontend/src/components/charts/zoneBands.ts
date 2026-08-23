/**
 * zoneBands.ts — shaded price-band rendering.
 *
 * DESIGN NOTE (why this doesn't use a custom drawing primitive): lightweight-
 * charts v5 does support fully custom drawing via ISeriesPrimitive, but that
 * means hand-writing raw canvas draw() code against a low-level API. Given
 * how much of this rebuild exists specifically because past hand-rolled
 * canvas/overlay code (absolutely-positioned divs recalculated on pan/zoom,
 * custom wheel handlers, manual overlay timing) kept breaking, this uses the
 * library's own native `Baseline` series instead: one series per band, with
 * `baseValue` set to the band's lower edge and a single data point at the
 * band's upper edge, filled with a translucent color, scoped to a specific
 * time range. It's a native, first-party rendering path — it inherits
 * correct pan/zoom/resize behavior for free instead of us re-implementing it.
 *
 * The one thing this approach can't do is fill between two lines that BOTH
 * move over time (e.g. VWAP's ±1σ band, where the upper and lower edges
 * change every bar). Those stay as two plain lines (already implemented in
 * TradeChartEngine) rather than a shaded fill, to avoid taking on that risk.
 */
import { BaselineSeries } from "lightweight-charts";
import type { IChartApi, ISeriesApi, Time } from "lightweight-charts";

export interface ZoneBandSpec {
  id: string;          // stable key — used to diff against previously-drawn bands
  fromTime: Time;
  toTime: Time;
  low: number;
  high: number;
  color: string;       // rgba(...) or #rrggbbaa — should already include desired opacity
  label?: string;
}

/** Tracks one Baseline series per active zone id and keeps the chart in sync. */
export class ZoneBandManager {
  private chart: IChartApi;
  private series = new Map<string, ISeriesApi<"Baseline">>();

  constructor(chart: IChartApi) {
    this.chart = chart;
  }

  sync(specs: ZoneBandSpec[]) {
    const nextIds = new Set(specs.map((s) => s.id));

    // Remove bands that are no longer requested.
    for (const [id, series] of this.series) {
      if (!nextIds.has(id)) {
        try { this.chart.removeSeries(series); } catch { /* already gone */ }
        this.series.delete(id);
      }
    }

    for (const spec of specs) {
      if (!(spec.high > spec.low)) continue;   // guard against inverted/zero-height bands
      let series = this.series.get(spec.id);
      if (!series) {
        series = this.chart.addSeries(BaselineSeries, {
          baseValue: { type: "price", price: spec.low },
          topLineColor: "transparent",
          bottomLineColor: "transparent",
          bottomFillColor1: "transparent",
          bottomFillColor2: "transparent",
          priceLineVisible: false,
          lastValueVisible: false,
          crosshairMarkerVisible: false,
          // Decorative bands must never stretch/compress the candle scale.
          autoscaleInfoProvider: () => null,
        }) as unknown as ISeriesApi<"Baseline">;
        this.series.set(spec.id, series);
      }
      series.applyOptions({
        baseValue: { type: "price", price: spec.low },
        topFillColor1: spec.color,
        topFillColor2: spec.color,
      });
      series.setData([
        { time: spec.fromTime, value: spec.high },
        { time: spec.toTime, value: spec.high },
      ]);
    }
  }

  destroy() {
    for (const series of this.series.values()) {
      try { this.chart.removeSeries(series); } catch { /* chart already disposed */ }
    }
    this.series.clear();
  }
}

export function toEpochTime(iso: string): Time {
  return (new Date(iso).getTime() / 1000) as Time;
}
