/**
 * App.tsx — Root component. Wires router, auth, WebSocket, React Query, layout shell.
 *
 * Auth flow:
 *  1. AuthProvider checks /api/auth/me on mount.
 *  2. While checking → show <Maintenance mode="connecting" />.
 *  3. If unauthenticated → show <Login />.
 *  4. If authenticated → show AppShell with all routes.
 */
import { HashRouter, Routes, Route } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useWebSocket }    from "./hooks/useWebSocket";
import { AuthProvider, useAuth } from "./contexts/AuthContext";
import { Topbar }          from "./components/layout/Topbar";
import { Sidebar }         from "./components/layout/Sidebar";
import { TickerBar }       from "./components/layout/TickerBar";
import { LiveTrading }     from "./pages/LiveTrading";
import { Performance }     from "./pages/Performance";
import { Journal }         from "./pages/Journal";
import { Settings }        from "./pages/Settings";
import { Backtest }        from "./pages/Backtest";
import { Playbooks }       from "./pages/Playbooks";
import { DailyBrief }      from "./pages/DailyBrief";
import { Login }           from "./pages/Login";
import { Maintenance }     from "./pages/Maintenance";

const qc = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 5 * 60_000,      // data is fresh for 5 min — switching tabs within 5 min
                                  // always uses the cache instantly with no loading state
      gcTime:    10 * 60_000,     // keep unused cache for 10 min so back-nav is instant
      retry: 1,                   // one retry max; avoid 3s backoff delay on tab click
      refetchOnWindowFocus: false, // clicking a tab re-focuses the window → was triggering mass refetch
      // Keep showing previous data while a background refetch runs.
      // Without this, every tab switch after staleTime shows a blank skeleton.
      placeholderData: (prev: unknown) => prev,
    },
  },
});

// ── Inner shell — only rendered when authenticated ─────────────────────────────
function AppShell() {
  // Connect WebSocket on mount; feeds Zustand bot store
  useWebSocket();

  return (
    <div className="app-shell">
      <Topbar />
      <Sidebar />
      <main className="app-main" style={{ paddingBottom: 36 }}>
        <Routes>
          <Route path="/"            element={<LiveTrading />} />
          <Route path="/performance" element={<Performance />} />
          <Route path="/journal"     element={<Journal />} />
          <Route path="/backtest"    element={<Backtest />} />
          <Route path="/playbooks"   element={<Playbooks />} />
          <Route path="/settings"    element={<Settings />} />
          <Route path="/daily-brief" element={<DailyBrief />} />
        </Routes>
      </main>
      <TickerBar />
    </div>
  );
}

// ── Auth gate — decides what to render based on session state ──────────────────
function AuthGate() {
  const { isAuthenticated, loading } = useAuth();

  // Still checking session cookie → branded loading screen
  if (loading) return <Maintenance mode="connecting" />;

  // Not logged in → login page
  if (!isAuthenticated) return <Login />;

  // Authenticated → full app
  return <AppShell />;
}

// ── Root ───────────────────────────────────────────────────────────────────────
export default function App() {
  return (
    <QueryClientProvider client={qc}>
      <AuthProvider>
        {/* HashRouter: navigation is always client-side (URL becomes /#/page).
            Eliminates any server-routing edge cases with the FastAPI catch-all. */}
        <HashRouter>
          <AuthGate />
        </HashRouter>
      </AuthProvider>
    </QueryClientProvider>
  );
}
