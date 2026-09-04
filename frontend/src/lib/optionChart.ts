export interface OptionChartData {
  trade_id: number; mode: "paper" | "live"; ticker: string; contract_symbol: string;
  option_type: string; strike: number | null; expiry: string; contracts: number;
  entry_price: number | null; entry_time: number | null;
  exit_price: number | null; exit_time: number | null; realized_pnl: number | null;
  stop_price: number | null; target_price: number | null; closed: boolean;
  quotes: { time: number; bid: number; ask: number }[]; truncated: boolean; as_of: number;
}

export const optionMoney = (value: number | null | undefined) =>
  value == null ? "—" : new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(value);

export function optionMetrics(data: OptionChartData, now = Date.now() / 1000) {
  const quote = data.quotes.at(-1);
  const age = quote ? Math.max(0, now - quote.time) : null;
  const stale = !data.closed && (age == null || age > 120);
  const price = data.closed ? data.exit_price : quote?.bid ?? null;
  const entry = data.entry_price;
  const pnl = data.closed ? data.realized_pnl
    : price != null && entry != null ? (price - entry) * data.contracts * 100 : null;
  return { quote, age, stale, price, pnl,
    value: price == null ? null : price * data.contracts * 100,
    target: entry != null && data.target_price != null && data.target_price > entry ? data.target_price : null,
    stop: entry != null && data.stop_price != null && data.stop_price >= 0 && data.stop_price < entry ? data.stop_price : null,
  };
}

export function quoteSegments(quotes: OptionChartData["quotes"]) {
  // Leave visible gaps when capture stopped; do not imply a continuous price feed.
  const segments: OptionChartData["quotes"][] = [];
  for (const quote of quotes) {
    const last = segments.at(-1)?.at(-1);
    if (!last || quote.time - last.time > 120) segments.push([]);
    segments.at(-1)!.push(quote);
  }
  return segments;
}
