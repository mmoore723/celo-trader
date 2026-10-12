import type { Data, Layout, Shape, Annotations } from "plotly.js";
import type { OptionChartData } from "./optionChart";

const et = (stamp: number) => new Date(stamp * 1000).toLocaleString("sv-SE", { timeZone: "America/New_York" });
const money = (n: number) => `$${n.toFixed(2)}`;

export function optionPositionFigure(data: OptionChartData, dark = false) {
  const candles = data.candles.filter(c => [c.time, c.open, c.high, c.low, c.close].every(Number.isFinite))
    .sort((a, b) => a.time - b.time);
  const traces: Data[] = [{
    type: "candlestick", name: data.contract_symbol,
    x: candles.map(c => et(c.time)), open: candles.map(c => c.open),
    high: candles.map(c => c.high), low: candles.map(c => c.low), close: candles.map(c => c.close),
    increasing: { line: { color: "#079455" } }, decreasing: { line: { color: "#e5484d" } },
  }];
  const shapes: Partial<Shape>[] = [];
  const annotations: Partial<Annotations>[] = [];
  const entry = data.entry_price;
  const start = data.entry_time;
  const end = data.closed ? data.exit_time : data.as_of;
  if (entry != null && entry > 0 && start != null && end != null) {
    const stop = data.stop_price != null && data.stop_price >= 0 && data.stop_price < entry ? data.stop_price : null;
    const target = data.target_price != null && data.target_price > entry ? data.target_price : null;
    const ratio = stop != null && target != null ? ((target - entry) / (entry - stop)).toFixed(2) : null;
    for (const [name, level, color, fill] of [
      ["Target", target, "#079455", "rgba(7,148,85,0.17)"],
      ["Stop", stop, "#e5484d", "rgba(229,72,77,0.17)"],
      ["Entry", entry, dark ? "#d0d5dd" : "#475467", "transparent"],
    ] as const) {
      if (level == null) continue;
      if (name !== "Entry") shapes.push({ type: "rect", x0: et(start), x1: et(end),
        y0: Math.min(entry, level), y1: Math.max(entry, level), fillcolor: fill, line: { width: 0 }, layer: "below" });
      shapes.push({ type: "line", x0: et(start), x1: et(end), y0: level, y1: level, line: { color, dash: "dash", width: 1.5 } });
      const move = (level - entry) / entry * 100;
      const pnl = (level - entry) * data.contracts * 100;
      annotations.push({ x: et(start + (end - start) / 2), y: level, showarrow: false,
        yanchor: name === "Stop" ? "top" : "bottom", font: { color, size: 11 },
        bgcolor: dark ? "rgba(20,25,34,0.92)" : "rgba(255,255,255,0.92)",
        text: `${name} ${money(level)} | ${move >= 0 ? "+" : ""}${move.toFixed(1)}%<br>` +
          `${money(pnl)} | Qty ${data.contracts} | R:R ${ratio ? `1:${ratio}` : "unavailable"}` });
    }
    traces.push({ type: "scatter", mode: "text+markers", name: "Entry fill", x: [et(start)], y: [entry],
      text: ["BUY FILL"], textposition: "bottom center", marker: { symbol: "triangle-up", size: 14, color: "#175cd3" } });
    if (data.closed && data.exit_time != null && data.exit_price != null) traces.push({
      type: "scatter", mode: "text+markers", name: "Exit fill", x: [et(data.exit_time)], y: [data.exit_price],
      text: ["SELL FILL"], textposition: "top center", marker: { symbol: "triangle-down", size: 14, color: "#e5484d" },
    });
  }
  const layout: Partial<Layout> = {
    height: 480, autosize: true, showlegend: false, shapes, annotations,
    paper_bgcolor: "transparent", plot_bgcolor: "transparent",
    font: { color: dark ? "#e4e7ec" : "#344054" }, margin: { l: 55, r: 20, t: 30, b: 65 },
    uirevision: `${data.mode}:${data.trade_id}:${data.interval ?? "1min"}`,
    xaxis: { type: "date", automargin: true, nticks: 4, tickangle: 0,
      gridcolor: dark ? "#293341" : "#eef0f3",
      title: { text: `Eastern time | ${data.interval === "daily" ? "Daily option candles" : "1-minute option candles"}`, standoff: 20 },
      rangeslider: { visible: false }, range: data.window_start != null && data.window_end != null ? [et(data.window_start), et(data.window_end)] : undefined },
    yaxis: { title: { text: "Option premium ($)" }, gridcolor: dark ? "#293341" : "#eef0f3", tickprefix: "$", fixedrange: false },
  };
  return { traces, layout };
}
