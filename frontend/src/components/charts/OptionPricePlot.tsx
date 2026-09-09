import { useEffect, useRef, useState } from "react";
import { optionMetrics, optionMoney, type OptionChartData } from "../../lib/optionChart";
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

  const { stop, target, quote } = optionMetrics(data);
  const entry = data.entry_price;
  const candles = data.candles ?? [];
  const prices = [entry, stop, target, data.exit_price, quote?.bid,
    ...candles.flatMap(candle => [candle.low, candle.high])]
    .filter((price): price is number => price != null && Number.isFinite(price));
  if (entry == null || data.entry_time == null || prices.length === 0) {
    return <p className="p-4 text-sm">This trade has no recorded entry price to chart.</p>;
  }

  const low = Math.min(...prices), high = Math.max(...prices);
  const pad = Math.max((high - low) * 0.12, entry * 0.025, 0.02);
  const floor = Math.max(0, low - pad), ceiling = high + pad;
  const left = 14, right = width - 62, top = 20, priceBottom = 300;
  const volumeTop = 316, volumeBottom = 350, axisY = 376;
  const start = Math.min(data.entry_time, candles[0]?.time ?? data.entry_time);
  const finish = Math.max(start + 60, data.exit_time ?? data.as_of, candles.at(-1)?.time ?? start);
  const x = (time: number) => left + (time - start) / (finish - start) * (right - left);
  const y = (price: number) => priceBottom - (price - floor) / (ceiling - floor) * (priceBottom - top);
  const maxVolume = Math.max(1, ...candles.map(candle => candle.volume));
  const spacing = candles.length > 1
    ? Math.min(...candles.slice(1).map((candle, index) => Math.max(1, x(candle.time) - x(candles[index].time))))
    : 12;
  const bodyWidth = Math.max(2, Math.min(11, spacing * 0.68));

  return <div ref={host} style={{ background: palette.background }}>
    <svg width="100%" height="390" viewBox={`0 0 ${width} 390`} role="img"
      aria-label={`${data.ticker} exact option contract, real one-minute price candles from Tradier. Green and red areas are reference profit and loss levels.`}>
      {target != null && <rect data-testid="profit-zone" x={left} y={y(target)} width={right-left}
        height={Math.max(0, y(entry)-y(target))} fill={palette.up} fillOpacity={0.16} />}
      {stop != null && <rect data-testid="risk-zone" x={left} y={y(entry)} width={right-left}
        height={Math.max(0, y(stop)-y(entry))} fill={palette.down} fillOpacity={0.14} />}
      {[0, 1, 2, 3, 4].map(index => {
        const price = floor + (ceiling-floor)*index/4;
        return <g key={index}><line x1={left} x2={right} y1={y(price)} y2={y(price)} stroke={palette.border} />
          <text x={right+7} y={y(price)+4} fill={palette.text} fontSize={12}>{optionMoney(price)}</text></g>;
      })}
      {[[entry, "Entry", palette.text], [target, "Target", palette.up], [stop, "Stop", palette.down]]
        .map(([price, label, color]) => price != null && <g key={String(label)}>
          <line x1={left} x2={right} y1={y(Number(price))} y2={y(Number(price))} stroke={String(color)} strokeWidth={1.25} />
          <rect x={left+5} y={y(Number(price))-19} width={label === "Entry" ? 104 : 112} height={18} rx={3} fill={palette.background} fillOpacity={0.94} />
          <text x={left+10} y={y(Number(price))-6} fill={String(color)} fontSize={12} fontWeight={600}>{label} {optionMoney(Number(price))}</text>
        </g>)}

      {candles.map((candle) => {
        const rising = candle.close >= candle.open;
        const color = rising ? palette.up : palette.down;
        const candleX = x(candle.time);
        const bodyTop = y(Math.max(candle.open, candle.close));
        const bodyHeight = Math.max(2, Math.abs(y(candle.open)-y(candle.close)));
        const volumeHeight = candle.volume / maxVolume * (volumeBottom-volumeTop);
        const title = `${timeLabel(candle.time)} ET · O ${optionMoney(candle.open)} · H ${optionMoney(candle.high)} · L ${optionMoney(candle.low)} · C ${optionMoney(candle.close)} · Vol ${candle.volume}`;
        return <g key={candle.time} data-testid="option-candle">
          <line x1={candleX} x2={candleX} y1={y(candle.high)} y2={y(candle.low)} stroke={color} strokeWidth={1.2} />
          <rect x={candleX-bodyWidth/2} y={bodyTop} width={bodyWidth} height={bodyHeight}
            fill={color} fillOpacity={rising ? 0.72 : 0.88} stroke={color} />
          <rect x={candleX-bodyWidth/2} y={volumeBottom-volumeHeight} width={bodyWidth} height={volumeHeight}
            fill={color} fillOpacity={0.28} />
          <title>{title}</title>
        </g>;
      })}

      <line x1={left} x2={right} y1={volumeBottom} y2={volumeBottom} stroke={palette.border} />
      <text x={left} y={volumeTop-3} fill={palette.text} fontSize={10}>Volume</text>
      <circle cx={x(data.entry_time)} cy={y(entry)} r={5} fill={palette.background} stroke={palette.text} strokeWidth={2}>
        <title>Actual entry fill {optionMoney(entry)}</title>
      </circle>
      {data.exit_time != null && data.exit_price != null && <circle cx={x(data.exit_time)} cy={y(data.exit_price)} r={5}
        fill={palette.background} stroke={palette.text} strokeWidth={2}><title>Actual exit fill {optionMoney(data.exit_price)}</title></circle>}
      {[0, 0.5, 1].map(fraction => <text key={fraction} x={left+(right-left)*fraction} y={axisY}
        textAnchor={fraction === 0 ? "start" : fraction === 1 ? "end" : "middle"} fill={palette.text} fontSize={12}>
        {timeLabel(start+(finish-start)*fraction)}</text>)}
    </svg>
    {candles.length === 0 && <p className="px-4 pb-4 text-sm" role="status">
      No one-minute trades were returned for this exact option contract. Actual fills and reference levels are shown; no candles were invented.
    </p>}
  </div>;
}
