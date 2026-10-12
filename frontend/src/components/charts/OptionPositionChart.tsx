import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api, type Trade } from "../../lib/api";
import { useAuth } from "../../contexts/AuthContext";
import { optionMetrics, optionMoney, type OptionChartData } from "../../lib/optionChart";
import { OptionPricePlot } from "./OptionPricePlot";

export function OptionPositionView({ data }: { data: OptionChartData }) {
  const { price, pnl, value, stale, quote, target, stop } = optionMetrics(data);
  const entry = data.entry_price;
  const changeAt = (level: number | null) => level != null && entry != null
    ? optionMoney((level-entry)*data.contracts*100) : "—";
  return <section aria-label="Option position chart" style={{ background: "var(--surface)" }}>
    <div className="px-4 pt-4 pb-2 flex flex-wrap justify-between gap-3">
      <div><h3 className="font-semibold">{data.ticker} {data.strike} {data.option_type.toUpperCase()} · {data.expiry}</h3>
        <p className="text-xs text-ink-muted">Bought {data.contracts} {data.contracts === 1 ? "contract" : "contracts"} · {data.mode === "paper" ? "Paper" : "Live"}</p></div>
      <div className="text-right"><div className="text-xs text-ink-muted">{data.closed ? "Closed P&L" : stale ? "P&L at last quote" : "Estimated P&L at bid"}</div>
        <div className="text-xl font-semibold" style={{ color: pnl == null ? "var(--ink)" : pnl >= 0 ? "var(--positive)" : "var(--negative)" }}>{optionMoney(pnl)}</div></div>
    </div>
    <div className="grid grid-cols-3 gap-2 px-4 pb-3 text-sm">
      <div><div className="text-xs text-ink-muted">{data.closed ? "Exit fill" : "Last bid"}</div>{optionMoney(price)}</div>
      <div><div className="text-xs text-ink-muted">One contract × 100</div>{optionMoney(price == null ? null : price*100)}</div>
      <div><div className="text-xs text-ink-muted">{data.closed ? "Exit value" : "Position value"}</div>{optionMoney(value)}</div>
    </div>
    <OptionPricePlot data={data} />
    <div className="px-4 pb-4 text-xs text-ink-muted space-y-2">
      <div className="flex flex-wrap justify-between gap-2">
        <span>Reference target: {changeAt(target)} total</span><span>Reference stop: {changeAt(stop)} total</span>
      </div>
      <p>Reference levels, not automatic exit orders. P&amp;L is before fees. {stop == null || target == null ? "A recorded option stop or target is missing; no replacement level is invented." : ""}</p>
      <p role={stale ? "status" : undefined}>{data.closed ? "Closed P&L uses the recorded trade result and exit fill." : quote ? `Bid captured ${new Date(quote.time*1000).toLocaleTimeString("en-US", { timeZone: "America/New_York" })} ET${stale ? " - not a current price." : " · Tradier"}. Estimated liquidation value, not a guaranteed fill.` : "Waiting for an executable quote."}</p>
      <details><summary className="cursor-pointer">Price details</summary>
        <p className="pt-2">{data.contract_symbol}: {data.interval === "daily" ? "daily Tradier History candles, not one-minute bars" : "one-minute Tradier Time & Sales candles"}. BUY FILL and SELL FILL mark the recorded fill times and option prices. P&amp;L uses the latest available bid, not the candle close. Missing candles stay missing.{data.truncated ? " Latest 5,000 quote records shown." : ""}</p>
      </details>
    </div>
  </section>;
}

export function OptionPositionChart({ trade }: { trade: Trade }) {
  const { user } = useAuth();
  const mode = trade.mode === "live" ? "live" : "paper";
  const [interval, setInterval] = useState<"daily" | "1min">("daily");
  const { data, isError, isLoading, refetch } = useQuery({
    queryKey: ["option-chart", user?.user_id ?? user?.email, mode, trade.id, interval, trade.exit_time, trade.status, trade.contracts],
    queryFn: () => api.trades.optionChart(trade.id, mode, interval),
    enabled: !!user, gcTime: 0, staleTime: 0, retry: false, refetchInterval: 60_000,
  });
  if (isLoading) return <p role="status" className="p-6 text-sm">Loading recorded option prices…</p>;
  if (isError || !data) return <div role="alert" className="p-6 text-sm">Option prices could not be loaded. <button className="btn btn-sm btn-ghost" onClick={() => refetch()}>Try again</button></div>;
  return <><div className="p-3 flex flex-wrap gap-2" aria-label="Option candle interval">
    {(["daily", "1min"] as const).map(value => <button key={value} type="button" aria-pressed={interval === value}
      className={`btn btn-sm ${interval === value ? "btn-primary" : "btn-ghost"}`} onClick={() => setInterval(value)}>
      {value === "daily" ? "Daily option history" : "1-minute option candles"}</button>)}
    <button type="button" className="btn btn-sm btn-ghost" onClick={() => refetch()}>Refresh quote</button>
  </div><OptionPositionView data={data} /></>;
}
