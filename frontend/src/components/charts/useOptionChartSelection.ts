import { useState } from "react";
import type { Trade } from "../../lib/api";

export function useOptionChartSelection(ticker: string, trades: Trade[], selectTicker: (ticker: string) => void,
  expand: (value: boolean) => void, defaultView: "option" | "stock" = "stock",
  onSelectPosition?: () => void) {
  const [choice, setChoice] = useState<{ ticker: string; id: number; mode?: string; view: "option" | "stock" } | null>(null);
  const available = trades.filter(t => t.ticker === ticker)
    .filter((t, i, all) => all.findIndex(other => other.id === t.id && other.mode === t.mode) === i)
    .sort((a, b) => Number(!!a.exit_time)-Number(!!b.exit_time) || b.id-a.id);
  const selected = available.find(t => choice?.ticker === ticker && choice.id === t.id && choice.mode === t.mode) ?? available[0];
  const view = selected && choice?.id === selected.id && choice.mode === selected.mode && choice.ticker === ticker
    ? choice.view : defaultView;
  function selectOption(trade: Trade) {
    setChoice({ ticker: trade.ticker, id: trade.id, mode: trade.mode, view: defaultView });
    onSelectPosition?.();
    selectTicker(trade.ticker);
    expand(true);
    requestAnimationFrame(() => document.getElementById("live-market-chart")?.scrollIntoView({ block: "start" }));
  }
  function setView(next: "option" | "stock") {
    if (selected) setChoice({ ticker, id: selected.id, mode: selected.mode, view: next });
  }
  return { selected, available, view, selectOption, setView };
}
