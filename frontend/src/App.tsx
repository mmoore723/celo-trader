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
import { Register }        from "./pages/Register";
import { Login }           from "./pages/Login";
import { Terms }           from "./pages/Terms";
import { Maintenance }     from "./pages/Maintenance";
import { ApiSetupModal }   from "./components/ApiSetupModal";
import { ErrorBoundary }   from "./components/ErrorBoundary";
import { BrokerAlertBanner } from "./components/BrokerAlertBanner";
import { StrategyRecommendationModal } from "./components/StrategyRecommendationModal";
import { PageLoader } from "./components/PageLoader";
import { lazy, Suspense, useState, useEffect } from "react";

// Load each authenticated workspace only when the user opens it. The charting
// libraries are by far the largest dependency; keeping them out of the login,
// daily brief, and journal bundles makes first load faster and reduces the
// blast radius of a page-specific rendering failure.
const LiveTrading = lazy(() => import("./pages/LiveTrading").then((module) => ({ default: module.LiveTrading })));
const Performance = lazy(() => import("./pages/Performance").then((module) => ({ default: module.Performance })));
const Journal = lazy(() => import("./pages/Journal").then((module) => ({ default: module.Journal })));
const ScannerOpportunities = lazy(() => import("./pages/ScannerOpportunities").then((module) => ({ default: module.ScannerOpportunities })));
const Settings = lazy(() => import("./pages/Settings").then((module) => ({ default: module.Settings })));
const Backtest = lazy(() => import("./pages/Backtest").then((module) => ({ default: module.Backtest })));
const Playbooks = lazy(() => import("./pages/Playbooks").then((module) => ({ default: module.Playbooks })));
const DailyBrief = lazy(() => import("./pages/DailyBrief").then((module) => ({ default: module.DailyBrief })));
const AiReasoning = lazy(() => import("./pages/AiReasoning").then((module) => ({ default: module.AiReasoning })));
const Admin = lazy(() => import("./pages/Admin").then((module) => ({ default: module.Admin })));

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

  // Show API setup modal for new users who have no credentials yet.
  // Use localStorage so it only ever appears once per user, even if
  // credentials aren't migrated yet from the old config format.
  const { user } = useAuth();
  const [showSetup, setShowSetup] = useState(false);
  useEffect(() => {
    const dismissedKey = `celo_setup_done_${user?.user_id ?? "admin"}`;
    if (localStorage.getItem(dismissedKey)) return; // already seen
    fetch("/api/settings/credentials", { credentials: "include" })
      .then((r) => r.json())
      .then((d) => {
        const empty = !d.alpaca_key && !d.tradier_token;
        if (empty) setShowSetup(true);
      })
      .catch(() => {});
  }, [user?.user_id]);

  function closeSetup() {
    const dismissedKey = `celo_setup_done_${user?.user_id ?? "admin"}`;
    localStorage.setItem(dismissedKey, "1");
    setShowSetup(false);
  }

  return (
    <div className="app-shell">
      {showSetup && <ApiSetupModal onClose={closeSetup} />}
      {!showSetup && <StrategyRecommendationModal />}
      {/* Mascot watermark — fixed behind all page content */}
      <img
        src="/mascot.png"
        aria-hidden="true"
        style={{
          position: "fixed", top: "50%", left: "50%",
          transform: "translate(-50%, -50%)",
          width: 1100, height: 1100, objectFit: "contain",
          opacity: 0.07, filter: "grayscale(100%)",
          WebkitMaskImage: "radial-gradient(ellipse 50% 50% at 50% 50%, black 35%, transparent 70%)",
          maskImage: "radial-gradient(ellipse 50% 50% at 50% 50%, black 35%, transparent 70%)",
          pointerEvents: "none", userSelect: "none", zIndex: 2,
        }}
      />
      <BrokerAlertBanner />
      <Topbar />
      <Sidebar />
      <main className="app-main" style={{ paddingBottom: 36 }}>
        <ErrorBoundary>
        <Suspense fallback={<PageLoader label="Loading workspace" />}>
        <Routes>
          <Route path="/"            element={<DailyBrief />} />
          <Route path="/trading"     element={<LiveTrading />} />
          <Route path="/performance" element={<Performance />} />
          <Route path="/journal"     element={<Journal />} />
          <Route path="/opportunities" element={<ScannerOpportunities />} />
          <Route path="/backtest"    element={<Backtest />} />
          <Route path="/ai-reasoning" element={<AiReasoning />} />
          <Route path="/playbooks"   element={<Playbooks />} />
          <Route path="/settings"    element={<Settings />} />
          <Route path="/admin"       element={<AdminGuard />} />
          {/* Read-only terms view for already-accepted users */}
          <Route path="/terms"       element={<Terms viewOnly />} />
        </Routes>
        </Suspense>
        </ErrorBoundary>
      </main>
      <TickerBar />
    </div>
  );
}

// ── Admin guard — 403 for non-admins ──────────────────────────────────────────
function AdminGuard() {
  const { user } = useAuth();
  if (!user?.is_admin) return (
    <div className="p-8 text-center" style={{ color: "var(--ink-muted)" }}>
      Access denied — admin only.
    </div>
  );
  return <Admin />;
}

// ── Auth gate — decides what to render based on session state ──────────────────
function AuthGate() {
  const { isAuthenticated, loading, user } = useAuth();

  // Poll /api/bot/status to detect maintenance mode for non-admin users.
  // Admins always see the full app so they can clear the maintenance flag.
  const [maint, setMaint] = useState<{ active: boolean; message: string } | null>(null);
  useEffect(() => {
    if (!isAuthenticated || user?.is_admin) return;
    function check() {
      fetch("/api/bot/status", { credentials: "include" })
        .then(r => (r.ok ? r.json() : null))
        .then(d => {
          if (d) setMaint({ active: !!d.maintenance_mode, message: d.maintenance_message ?? "" });
        })
        .catch(() => {});
    }
    check();
    const t = setInterval(check, 30_000);
    return () => clearInterval(t);
  }, [isAuthenticated, user?.is_admin]);

  // Still checking session cookie → branded loading screen
  if (loading) return <Maintenance mode="connecting" />;

  // Not logged in → login page (register has its own public route below)
  if (!isAuthenticated) return <Login />;

  // Logged in but ToS not accepted (or older version) → show Terms gate
  if (!user?.terms_accepted) return <Terms />;

  // Maintenance mode active → non-admin users see the maintenance screen
  if (maint?.active && !user?.is_admin) {
    return (
      <Maintenance
        mode="maintenance"
        message={maint.message || "We'll be back soon. No trades are affected."}
      />
    );
  }

  // Authenticated + ToS accepted → full app
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
          <Routes>
            {/* Public routes — no auth required */}
            <Route path="/register" element={<Register />} />
            {/* Terms page public so the login-page ToS link works without being logged in */}
            <Route path="/terms"    element={<Terms viewOnly />} />
            {/* Everything else gates on auth */}
            <Route path="*" element={<AuthGate />} />
          </Routes>
        </HashRouter>
      </AuthProvider>
    </QueryClientProvider>
  );
}
