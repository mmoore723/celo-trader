/**
 * ErrorBoundary — catches render-time exceptions in any page and shows a
 * recoverable message instead of a blank white screen.
 *
 * Added 2026-07-17 after a shape mismatch between the Strategy Health page's
 * GET /latest and POST /run responses caused an uncaught exception during
 * render (`shown.aggregate` was undefined) that unmounted the entire app
 * with no error boundary in place. Wraps the routed page content in App.tsx.
 */
import { Component, type ReactNode } from "react";
import { isChunkLoadError, recoverPage } from "../lib/chunkRecovery.js";

interface Props { children: ReactNode; }
interface State { error: Error | null; }

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: { componentStack: string }) {
    console.error("ErrorBoundary caught a render error:", error, info.componentStack);
  }

  render() {
    if (this.state.error) {
      return (
        <div className="p-6" style={{ color: "var(--ink)" }}>
          <div className="card" style={{ padding: 20, maxWidth: 560 }}>
            <h2 style={{ fontSize: 15, fontWeight: 600, marginBottom: 8, color: "var(--negative)" }}>
              This page hit an error
            </h2>
            <p style={{ fontSize: 13, color: "var(--ink-muted)", marginBottom: 12 }}>
              {isChunkLoadError(this.state.error)
                ? "This page could not load its app files. Reload to fetch the current version. Reloading does not restart the trading bot."
                : this.state.error.message || "Unknown error"}
            </p>
            <button className="btn btn-ghost" onClick={() => recoverPage(this.state.error, () => window.location.reload(), () => this.setState({ error: null }))}>
              {isChunkLoadError(this.state.error) ? "Reload page" : "Try again"}
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
