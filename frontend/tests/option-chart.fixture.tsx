// Offline UI fixtures only. Never bundled into or served by the production app.
import { useState } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AuthProvider } from "../src/contexts/AuthContext";
import { OptionPositionChart } from "../src/components/charts/OptionPositionChart";
import { useOptionChartSelection } from "../src/components/charts/useOptionChartSelection";
import { useThemeStore } from "../src/store/theme";
import type { Trade } from "../src/lib/api";
import "../src/index.css";

const trades: Trade[] = [
  { id: 1, ticker: "SPY", entry_price: 4.13, contracts: 2, direction: "long", status: "open", mode: "paper" },
  { id: 2, ticker: "TSLA", entry_price: 1.8, contracts: 1, direction: "short", status: "open", mode: "paper" },
];
function Harness() {
  const [ticker, setTicker] = useState("SPY");
  const [expanded, setExpanded] = useState(false);
  const [poll, setPoll] = useState(0);
  const choice = useOptionChartSelection(ticker, trades.map(t => ({ ...t })), setTicker, setExpanded);
  return <main style={{ maxWidth: 850, margin: "20px auto" }}>
    <p className="p-3 text-sm">UI TEST DATA — not real trading results</p>
    <nav className="p-3 flex flex-wrap gap-2">
      {trades.map(t => <button className="btn btn-sm" key={t.id} onClick={() => choice.selectOption(t)}>Select {t.ticker}</button>)}
      <button className="btn btn-sm" onClick={() => choice.setView("stock")}>Stock price</button>
      <button className="btn btn-sm" onClick={() => choice.setView("option")}>Option price</button>
      <button className="btn btn-sm" onClick={() => setPoll(poll+1)}>Refresh state {poll}</button>
      <button className="btn btn-sm" onClick={() => useThemeStore.getState().toggle()}>Theme</button>
    </nav>
    <div className="card overflow-hidden">{expanded && (choice.view === "stock" ? <p>Stock chart preserved</p>
      : choice.selected && <OptionPositionChart trade={choice.selected} />)}</div>
  </main>;
}
createRoot(document.getElementById("root")!).render(<QueryClientProvider client={new QueryClient()}>
  <AuthProvider><Harness /></AuthProvider>
</QueryClientProvider>);
