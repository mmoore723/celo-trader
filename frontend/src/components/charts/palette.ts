/**
 * palette.ts — single color source for the chart engine (TradeChart + overlays).
 * Replaces the two separate `colors()` / `makeStyles()` functions that used to
 * live duplicated in TradingChart.tsx and KChart.tsx.
 */

export interface ChartPalette {
  background: string;
  text: string;
  grid: string;
  border: string;
  up: string;
  down: string;
  vwap: string;
  vwapBand1: string;
  vwapBand2: string;
  orHigh: string;
  orLow: string;
  volAvg: string;
  breakout: string;
  entry: string;
  stop: string;
  target: string;
  trail: string;
  structureUp: string;    // HH / HL — bullish structure
  structureDown: string;  // LH / LL — bearish structure
  choch: string;          // change-of-character marker
  bos: string;            // break-of-structure marker
  premium: string;        // upper-half-of-range shading
  discount: string;       // lower-half-of-range shading
  killzone: string;       // session-window shading
  rsi: string;
  rsiOB: string;
  rsiOS: string;
  rsiMid: string;
  macdLine: string;
  macdSignal: string;
  macdHistPos: string;
  macdHistNeg: string;
}

export function getPalette(dark: boolean): ChartPalette {
  return {
    background:    dark ? "#131722" : "#ffffff",
    text:          dark ? "#848e9c" : "#5a6476",
    grid:          dark ? "#1e222d" : "#f0f2f7",
    border:        dark ? "#2a2e39" : "#e2e5ed",
    up:            dark ? "#26a69a" : "#089981",
    down:          dark ? "#ef5350" : "#f23645",
    vwap:          dark ? "#58a6ff" : "#2563eb",
    vwapBand1:     dark ? "#58a6ff33" : "#2563eb26",
    vwapBand2:     dark ? "#58a6ff1a" : "#2563eb14",
    orHigh:        dark ? "#4ade80" : "#16a34a",
    orLow:         dark ? "#f87171" : "#dc2626",
    volAvg:        dark ? "#9ca3af" : "#6b7280",
    breakout:      "#f59e0b",
    entry:         "#eab308",
    stop:          "#dc2626",
    target:        "#16a34a",
    trail:         "#9333ea",
    structureUp:   dark ? "#4ade80" : "#15803d",
    structureDown: dark ? "#ff6b6b" : "#cc0000",
    choch:         "#f59e0b",   // amber — "something changed, pay attention"
    bos:           "#8b5cf6",   // violet — matches backend's TREND_CONT/BOS_MSS color family
    premium:       dark ? "#ef535014" : "#f2364514",   // faint red tint — upper half of range
    discount:      dark ? "#26a69a14" : "#08998114",   // faint teal tint — lower half of range
    killzone:      dark ? "#58a6ff0d" : "#2563eb0d",   // very faint blue — session window
    rsi:           dark ? "#a78bfa" : "#7c3aed",
    rsiOB:         dark ? "#f87171" : "#dc2626",
    rsiOS:         dark ? "#4ade80" : "#16a34a",
    rsiMid:        dark ? "#374151" : "#d1d5db",
    macdLine:      dark ? "#f59e0b" : "#d97706",
    macdSignal:    dark ? "#e879f9" : "#9333ea",
    macdHistPos:   dark ? "#26a69a" : "#089981",
    macdHistNeg:   dark ? "#ef5350" : "#f23645",
  };
}
