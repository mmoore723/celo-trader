import type { Bar, Trade } from "../../lib/api";
import { optionMetrics, type OptionChartData } from "../../lib/optionChart";
import { TradeChart } from "./TradeChart";

function candleTime(data: OptionChartData, stamp: number | null): string | undefined {
  if (stamp == null || data.candles.length === 0) return undefined;
  const nearest = data.candles.reduce((best, candle) =>
    Math.abs(candle.time - stamp) < Math.abs(best.time - stamp) ? candle : best,
  );
  return new Date(nearest.time * 1000).toISOString();
}

export function OptionPricePlot({ data }: { data: OptionChartData }) {
  const metrics = optionMetrics(data);
  const bars: Bar[] = [...(data.candles ?? [])]
    .filter((candle) => [candle.open, candle.high, candle.low, candle.close, candle.volume]
      .every(Number.isFinite))
    .sort((left, right) => left.time - right.time)
    .map((candle) => ({
      time: new Date(candle.time * 1000).toISOString(),
      open: candle.open,
      high: candle.high,
      low: candle.low,
      close: candle.close,
      volume: candle.volume,
    }));

  if (data.entry_price == null || data.entry_time == null) {
    return <p className="p-4 text-sm">This trade has no recorded entry price to chart.</p>;
  }
  if (bars.length === 0) {
    return <p className="p-6 text-sm" role="status">
      No one-minute trades were returned for this exact option contract. No candles were invented.
    </p>;
  }

  const chartTrade: Trade = {
    id: data.trade_id,
    contract_symbol: data.contract_symbol,
    strike: data.strike ?? undefined,
    expiry: data.expiry,
    ticker: data.ticker,
    direction: "long",
    option_type: data.option_type,
    entry_price: data.entry_price,
    exit_price: data.exit_price ?? undefined,
    contracts: data.contracts,
    pnl: metrics.pnl ?? undefined,
    status: data.closed ? "closed" : "open",
    entry_time: candleTime(data, data.entry_time),
    exit_time: candleTime(data, data.exit_time),
  };

  return <TradeChart
    bars={bars}
    trades={[chartTrade]}
    ticker={`${data.ticker} ${data.strike ?? ""} ${data.option_type.toUpperCase()}`.trim()}
    height={430}
    viewportKey={`option-position:${data.mode}:${data.trade_id}`}
    minuteTimelineStart={new Date((data.window_start ?? data.entry_time - 20 * 60) * 1000).toISOString()}
    minuteTimelineEnd={new Date((data.window_end ?? Math.min((data.exit_time ?? data.as_of) + (data.exit_time ? 20 * 60 : 0), data.as_of)) * 1000).toISOString()}
    showVwap={false}
    showVwapBands={false}
    showOR={false}
    showSwings={false}
    showStructure={false}
    showExecutionGrade={false}
    showRsi={false}
    showMacd={false}
    showPositionCard
    currentOptionPrice={metrics.price}
    positionLevels={{
      entry: data.entry_price,
      stop: metrics.stop ?? undefined,
      target: metrics.target ?? undefined,
      direction: "long",
      contracts: data.contracts,
    }}
    positionLevelsOnCandleScale
  />;
}
