/**
 * chartMarkers.ts — builds the marker set (trade entry/exit, swing structure
 * + BOS/CHoCH, bot signal/veto markers) for one candle series. Split out of
 * chartOverlays.ts to keep each file focused and under the project's
 * per-file line limit.
 */
import { createSeriesMarkers } from "lightweight-charts";
import type { ISeriesApi, SeriesMarker, Time } from "lightweight-charts";
import type { OverlayInputs } from "./chartOverlays";
import type { ChartPalette } from "./palette";
import { detectSwings, classifyStructure } from "./marketStructure";
import { gradeBar } from "./executionGrade";
import { toEpochTime } from "./zoneBands";

export function buildAndApplyMarkers(candle: ISeriesApi<"Candlestick">, input: OverlayInputs, P: ChartPalette) {
  const markers: SeriesMarker<Time>[] = [];

  for (const t of input.trades) {
    if (t.entry_time) {
      const grade = input.showExecutionGrade ? gradeBar(input.bars.find((b) => b.time <= t.entry_time!) ?? input.bars[0]) : null;
      markers.push({ time: toEpochTime(t.entry_time), position: "belowBar", color: P.up, shape: "arrowUp", text: grade ? `BUY (${grade.grade})` : "BUY", size: 2 });
    }
    if (t.exit_time) markers.push({ time: toEpochTime(t.exit_time), position: "aboveBar", color: P.down, shape: "arrowDown", text: t.exit_reason ?? "SELL", size: 2 });
  }

  if (input.showSwings) {
    const swings = classifyStructure(detectSwings(input.bars, 3));
    for (const sw of swings) {
      const isHigh = sw.kind === "SH";
      const color = sw.label === "HH" || sw.label === "HL" ? P.structureUp : P.structureDown;
      let text = sw.label as string;
      if (input.showStructure && sw.structure) text = `${sw.label} · ${sw.structure === "choch" ? "CHoCH" : "BOS"}`;
      markers.push({ time: toEpochTime(sw.time), position: isHigh ? "aboveBar" : "belowBar", color: sw.structure === "choch" ? P.choch : color, shape: isHigh ? "arrowDown" : "arrowUp", text, size: sw.structure ? 2 : 1 });
    }
  }

  for (const ann of input.annotations) {
    if (ann.type === "marker" && ann.price != null) {
      const isBullish = ann.direction === "bullish";
      markers.push({ time: toEpochTime(ann.ts), position: isBullish ? "belowBar" : "aboveBar", color: ann.color, shape: ann.strategy === "veto" ? "square" : isBullish ? "arrowUp" : "arrowDown", text: ann.label, size: ann.strategy === "veto" ? 1 : 2 });
    }
  }

  markers.sort((a, b) => (a.time as number) - (b.time as number));
  createSeriesMarkers(candle, markers);
}
