/**
 * App.tsx — Root component. Wires router, WebSocket, React Query, layout shell.
 */
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useWebSocket } from "./hooks/useWebSocket";
import { Topbar }      from "./components/layout/Topbar";
import { Sidebar }     from "./components/layout/Sidebar";
import { LiveTrading } from "./pages/LiveTrading";
import { Performance } from "./pages/Performance";
import { Journal }     from "./pages/Journal";
import { Settings }    from "./pages/Settings";
import { Backtest }    from "./pages/Backtest";
import { Playbooks }   from "./pages/Playbooks";
import { DailyBrief }  from "./pages/DailyBrief";

const qc = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 5_000,
      retry: 2,
    },
  },
});

function AppShell() {
  // Connect WebSocket on mount; feeds Zustand bot store
  useWebSocket();

  return (
    <div className="app-shell">
      <Topbar />
      <Sidebar />
      <main className="app-main">
        <Routes>
          <Route path="/"           element={<LiveTrading />} />
          <Route path="/performance" element={<Performance />} />
          <Route path="/journal"    element={<Journal />} />
          <Route path="/backtest"   element={<Backtest />} />
          <Route path="/playbooks"  element={<Playbooks />} />
          <Route path="/settings"   element={<Settings />} />
          <Route path="/daily-brief" element={<DailyBrief />} />
        </Routes>
      </main>
    </div>
  );
}

export default function App() {
  return (
    <QueryClientProvider client={qc}>
      <BrowserRouter>
        <AppShell />
      </BrowserRouter>
    </QueryClientProvider>
  );
}
