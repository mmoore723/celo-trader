/**
 * TickerBar — scrolling live price tape pinned to viewport bottom.
 * Polls /api/market/quotes every 60 s for fresh prices.
 */
import { useQuery } from "@tanstack/react-query";
import { api } from "../../lib/api";

const SYMBOLS = ["SPY", "QQQ", "AAPL", "NVDA", "TSLA", "AMD", "MSFT", "AMZN", "META", "AMC"];

export function TickerBar() {
  const { data: quotes = [] } = useQuery({
    queryKey: ["ticker-bar"],
    queryFn:  () => api.market.quotes(SYMBOLS.join(",")),
    refetchInterval: 60_000,
    staleTime: 55_000,
  });

  // Build items from quotes; fall back to symbol-only for anything missing
  const items = SYMBOLS.map((sym) => {
    const q = quotes.find((r: { ticker: string }) => r.ticker === sym);
    if (!q) return { sym, price: null, chg: null };
    return { sym, price: q.price, chg: q.change_pct };
  });

  // Duplicate for seamless infinite scroll
  const rendered = [...items, ...items].map((item, i) => {
    const up   = item.chg == null ? null : item.chg >= 0;
    const arrow = up == null ? "" : up ? "▲" : "▼";
    const color = up == null
      ? "var(--ink-muted)"
      : up ? "var(--positive)" : "var(--negative)";

    return (
      <span key={i} style={{ display: "inline-flex", alignItems: "center", gap: 4, marginRight: 28 }}>
        <span style={{ fontWeight: 700, color: "var(--ink)", fontSize: 11 }}>{item.sym}</span>
        {item.price != null && (
          <span style={{ color: "var(--ink-muted)", fontSize: 11 }}>
            ${item.price.toFixed(2)}
          </span>
        )}
        {item.chg != null && (
          <span style={{ color, fontSize: 11 }}>
            {arrow} {item.chg >= 0 ? "+" : ""}{item.chg.toFixed(2)}%
          </span>
        )}
      </span>
    );
  });

  return (
    <div
      style={{
        position:   "fixed",
        bottom:     0,
        left:       0,
        right:      0,
        height:     28,
        background: "var(--surface)",
        borderTop:  "1px solid var(--border)",
        overflow:   "hidden",
        zIndex:     100,
        display:    "flex",
        alignItems: "center",
      }}
    >
      <div style={{ animation: "ticker-scroll 40s linear infinite", display: "inline-flex", whiteSpace: "nowrap", paddingLeft: "100%" }}>
        {rendered}
      </div>

      <style>{`
        @keyframes ticker-scroll {
          0%   { transform: translateX(0); }
          100% { transform: translateX(-50%); }
        }
      `}</style>
    </div>
  );
}
