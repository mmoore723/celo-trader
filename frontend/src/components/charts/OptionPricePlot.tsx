import { useEffect, useRef, useState } from "react";
import type { OptionChartData } from "../../lib/optionChart";
import { optionPositionFigure } from "../../lib/optionPositionFigure";
import { useThemeStore } from "../../store/theme";

export function OptionPricePlot({ data }: { data: OptionChartData }) {
  const node = useRef<HTMLDivElement>(null);
  const theme = useThemeStore(s => s.theme);
  const [error, setError] = useState(false);
  useEffect(() => {
    if (!node.current || !data.candles.length) return;
    const element = node.current;
    let disposed = false;
    let cleanup = () => {};
    import("plotly.js-finance-dist-min").then(async ({ default: plotly }) => {
      if (disposed) return;
      const figure = optionPositionFigure(data, theme === "dark");
      await plotly.react(element, figure.traces, figure.layout, { responsive: true, displaylogo: false, scrollZoom: true });
      if (disposed) { plotly.purge(element); return; }
      const resize = new ResizeObserver(() => {
        if (!disposed && element.clientWidth > 0) void Promise.resolve(plotly.Plots.resize(element)).catch(() => {});
      });
      resize.observe(element);
      cleanup = () => { resize.disconnect(); plotly.purge(element); };
    }).catch(() => { if (!disposed) setError(true); });
    return () => { disposed = true; cleanup(); };
  }, [data, theme]);
  if (!data.candles.length) return <p className="p-6 text-sm" role="status">
    No {data.interval === "daily" ? "daily" : "one-minute"} candles returned for {data.contract_symbol}. No stock prices or invented candles are substituted.
  </p>;
  if (error) return <p role="alert" className="p-4">Chart could not render. Refresh to retry.</p>;
  return <div ref={node} className="w-full min-w-0" role="img" aria-label={`${data.contract_symbol} option candles with actual entry and exit fills and risk reward boxes`} />;
}
