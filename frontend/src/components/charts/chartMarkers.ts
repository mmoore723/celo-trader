/**
 * chartMarkers.ts — builds the marker set (trade entry/exit, swing structure
 * + BOS/CHoCH, bot signal/veto markers) for one candle series. Split out of
 * chartOverlays.ts to keep each file focused and under the project's
 * per-file line limit.
 */
import { createSeriesMarkers } from "lightweight-charts";
import type { ISeriesApi, ISeriesMarkersPluginApi, SeriesMarker, Time } from "lightweight-charts";
import type { OverlayInputs } from "./chartOverlays";
import type { ChartPalette } from "./palette";
import { structureLabels } from "./marketStructure";
import { gradeBeforeEntry } from "./executionGrade";
import { toEpochTime } from "./zoneBands";

/**
 * Builds the marker set and pushes it to the chart. `existing` is the
 * marker-primitive handle from the PREVIOUS call (or null on first call).
 * createSeriesMarkers() attaches a brand-new primitive to the series every
 * time it's invoked — it does not replace one that's already attached. Since
 * apply() (and therefore this function) runs on every bars/annotations tick
 * during replay playback, calling createSeriesMarkers() fresh each time was
 * stacking a new, independent marker set on top of the series every ~125-
 * 500ms without ever removing the old ones — after a replay ran for a while,
 * dozens of overlapping generations of labels were all still being drawn at
 * once, which is what produced the illegible pile-up of BOS/CHoCH/swing
 * labels. Fix: create the primitive once, then reuse it via .setMarkers()
 * on every subsequent call — the library's own recommended update pattern.
 */
export function buildAndApplyMarkers(
  candle: ISeriesApi<"Candlestick">,
  input: OverlayInputs,
  P: ChartPalette,
  existing: ISeriesMarkersPluginApi<Time> | null,
): ISeriesMarkersPluginApi<Time> {
  const markers: SeriesMarker<Time>[] = [];

  for (const t of input.trades) {
    if (t.entry_time) {
      const grade = input.showExecutionGrade ? gradeBeforeEntry(input.bars, t.entry_time) : null;
      const option = t.option_type?.toUpperCase();
      const buy = option === "CALL" || option === "PUT" ? `BUY ${option}` : "BUY";
      markers.push({ time: toEpochTime(t.entry_time), position: "belowBar", color: P.up, shape: "arrowUp", text: grade ? `${buy} · prior candle: ${grade.grade}` : buy, size: 2 });
    }
    if (t.exit_time) markers.push({ time: toEpochTime(t.exit_time), position: "aboveBar", color: P.down, shape: "arrowDown", text: t.exit_reason ?? "SELL", size: 2 });
  }

  if (input.showSwings) {
    for (const label of structureLabels(input.bars, input.showStructure).slice(-18)) {
      const up = label.direction === "up";
      markers.push({ time:toEpochTime(label.time), position:up ? "belowBar" : "aboveBar",
        color:label.direction === "neutral" ? P.choch : up ? P.structureUp : P.structureDown,
        shape:label.event ? (up ? "arrowUp" : "arrowDown") : "circle",
        text:label.text, size:label.event ? 2 : 1 });
    }
  }

  for (const ann of input.annotations) {
    if (ann.type === "marker" && ann.price != null) {
      // Strategy annotations can also contain structure shorthand. Respect
      // the same Structure toggle so disabling it truly declutters the chart.
      const isStructureAnnotation = /(?:^|[\s·:_-])(HH|HL|LH|LL|SH|SL|BOS|CHOCH)(?:$|[\s·:_-])/i.test(ann.label);
      // Legacy annotations lack confirmation timestamps. Suppress hindsight arrows.
      if (isStructureAnnotation) continue;
      const isBullish = ann.direction === "bullish";
      markers.push({ time: toEpochTime(ann.ts), position: isBullish ? "belowBar" : "aboveBar", color: ann.color, shape: ann.strategy === "veto" ? "square" : isBullish ? "arrowUp" : "arrowDown", text: ann.label, size: ann.strategy === "veto" ? 1 : 2 });
    }
  }

  // Fair-value-gap fill percentage — how much of the gap price re-entered before
  // reversing, computed straight from the zone's own price_low/price_high
  // (already captured by the bot at signal time) plus the bars already on
  // screen. No backend change needed: this is pure frontend arithmetic on
  // data that was already flowing through.
  for (const ann of input.annotations) {
    if (ann.type !== "zone" || !ann.strategy?.includes("FVG") || ann.price_low == null || ann.price_high == null) continue;
    const gapLow = ann.price_low, gapHigh = ann.price_high;
    const gapSize = gapHigh - gapLow;
    if (gapSize <= 0) continue;
    const annMs = new Date(ann.ts).getTime();
    const isBullish = ann.direction === "bullish";
    let deepestPct = 0;
    let deepestBar: typeof input.bars[number] | null = null;
    for (const b of input.bars) {
      if (new Date(b.time).getTime() <= annMs) continue;   // only bars after the gap formed
      // Bullish FVG: price is expected to dip back DOWN into the gap from
      // above — fill % measured from the top edge downward. Bearish is the
      // mirror image (price rallies UP into the gap from below).
      const pct = isBullish
        ? Math.max(0, Math.min(100, ((gapHigh - b.low) / gapSize) * 100))
        : Math.max(0, Math.min(100, ((b.high - gapLow) / gapSize) * 100));
      if (pct > deepestPct) { deepestPct = pct; deepestBar = b; }
    }
    if (deepestBar && deepestPct > 0) {
      markers.push({
        time: toEpochTime(deepestBar.time), position: isBullish ? "belowBar" : "aboveBar",
        color: ann.color, shape: "circle", text: `FVG ${Math.round(deepestPct)}% filled`, size: 1,
      });
    }
  }

  markers.sort((a, b) => (a.time as number) - (b.time as number));

  if (existing) {
    existing.setMarkers(markers);
    return existing;
  }
  return createSeriesMarkers(candle, markers);
}
