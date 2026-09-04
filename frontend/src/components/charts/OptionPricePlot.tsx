import { useEffect, useRef, useState } from "react";
import { optionMetrics, optionMoney, quoteSegments, type OptionChartData } from "../../lib/optionChart";
import { getPalette } from "./palette";
import { useThemeStore } from "../../store/theme";

const timeLabel = (time: number) => new Date(time * 1000).toLocaleTimeString("en-US", {
  timeZone: "America/New_York", hour: "numeric", minute: "2-digit",
});

export function OptionPricePlot({ data }: { data: OptionChartData }) {
  const host = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(700);
  const palette = getPalette(useThemeStore((s) => s.theme) === "dark");
  useEffect(() => {
    const observer = new ResizeObserver(([entry]) => setWidth(Math.max(280, entry.contentRect.width)));
    if (host.current) observer.observe(host.current);
    return () => observer.disconnect();
  }, []);
  const { stop, target } = optionMetrics(data);
  const entry = data.entry_price;
  const prices = [entry, stop, target, data.exit_price, ...data.quotes.flatMap(q => [q.bid, q.ask])]
    .filter((p): p is number => p != null && Number.isFinite(p));
  if (entry == null || data.entry_time == null || prices.length === 0) {
    return <p className="p-4 text-sm">This trade has no recorded entry price to chart.</p>;
  }
  const low = Math.min(...prices), high = Math.max(...prices);
  const pad = Math.max((high - low) * 0.12, entry * 0.025, 0.02);
  const floor = Math.max(0, low - pad), ceiling = high + pad;
  const left = 14, right = width - 62, top = 20, bottom = 315;
  const start = data.entry_time;
  const finish = Math.max(start + 60, data.exit_time ?? data.as_of, data.quotes.at(-1)?.time ?? start);
  const x = (t: number) => left + (t - start) / (finish - start) * (right - left);
  const y = (p: number) => bottom - (p - floor) / (ceiling - floor) * (bottom - top);
  const path = (points: OptionChartData["quotes"], field: "bid" | "ask") =>
    points.map((q, i) => `${i ? "L" : "M"}${x(q.time)},${y(q[field])}`).join(" ");
  return <div ref={host} style={{ background: palette.background }}>
    <svg width="100%" height="350" viewBox={`0 0 ${width} 350`} role="img"
      aria-label={`${data.ticker} option price. Blue is recorded bid, dashed blue is ask. Green and red areas are reference profit and loss levels.`}>
      {target != null && <rect data-testid="profit-zone" x={left} y={y(target)} width={right-left}
        height={y(entry)-y(target)} fill={palette.up} fillOpacity={0.2} />}
      {stop != null && <rect data-testid="risk-zone" x={left} y={y(entry)} width={right-left}
        height={y(stop)-y(entry)} fill={palette.down} fillOpacity={0.18} />}
      {[0, 1, 2, 3, 4].map(i => {
        const price = floor + (ceiling-floor)*i/4;
        return <g key={i}><line x1={left} x2={right} y1={y(price)} y2={y(price)} stroke={palette.border} />
          <text x={right+7} y={y(price)+4} fill={palette.text} fontSize={12}>{optionMoney(price)}</text></g>;
      })}
      {[[entry, "Entry", palette.text], [target, "Reference target", palette.up], [stop, "Reference stop", palette.down]]
        .map(([price, label, color]) => price != null && <g key={String(label)}>
          <line x1={left} x2={right} y1={y(Number(price))} y2={y(Number(price))} stroke={String(color)} strokeWidth={1.5} />
          <rect x={left+5} y={y(Number(price))-19} width={label === "Entry" ? 104 : 178} height={18} rx={3} fill={palette.background} fillOpacity={0.94} />
          <text x={left+10} y={y(Number(price))-6} fill={String(color)} fontSize={12} fontWeight={600}>{label} {optionMoney(Number(price))}</text>
        </g>)}
      {quoteSegments(data.quotes).map((segment, index) => <g key={index}>
        <path d={path(segment, "ask")} fill="none" stroke={palette.vwap} strokeOpacity={0.5} strokeDasharray="4 4" />
        <path d={path(segment, "bid")} fill="none" stroke={palette.vwap} strokeWidth={2.5} />
        {segment.map(q => <circle key={q.time} cx={x(q.time)} cy={y(q.bid)} r={3} fill={palette.vwap}>
          <title>{timeLabel(q.time)} ET · Bid {optionMoney(q.bid)} · Ask {optionMoney(q.ask)}</title>
        </circle>)}
      </g>)}
      <circle cx={x(start)} cy={y(entry)} r={5} fill={palette.background} stroke={palette.text} strokeWidth={2}>
        <title>Actual entry fill {optionMoney(entry)}</title>
      </circle>
      {data.exit_time != null && data.exit_price != null && <circle cx={x(data.exit_time)} cy={y(data.exit_price)} r={5}
        fill={palette.background} stroke={palette.text} strokeWidth={2}><title>Actual exit fill {optionMoney(data.exit_price)}</title></circle>}
      {[0, 0.5, 1].map(f => <text key={f} x={left+(right-left)*f} y={340}
        textAnchor={f === 0 ? "start" : f === 1 ? "end" : "middle"} fill={palette.text} fontSize={12}>
        {timeLabel(start+(finish-start)*f)}</text>)}
    </svg>
    {data.quotes.length === 0 && <p className="px-4 pb-3 text-sm">No recorded quotes yet. Only actual fills and reference levels are shown.</p>}
  </div>;
}
