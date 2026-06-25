/**
 * PageLoader — skeleton placeholder shown while a page's initial data loads.
 * Gives clear visual feedback that navigation happened, so users don't think
 * the tab click was ignored.
 */
export function PageLoader({ label }: { label: string }) {
  return (
    <div className="page-loading">
      {/* Page title hint so users know which page they navigated to */}
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 4 }}>
        <div className="skeleton sk-title" />
        <span style={{ color: "var(--ink-faint)", fontSize: 12 }}>{label}</span>
      </div>
      {/* Row skeletons */}
      <div className="skeleton sk-row" style={{ width: "60%" }} />
      <div className="skeleton sk-row" style={{ width: "80%" }} />
      {/* Card skeletons */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 12 }}>
        <div className="skeleton sk-card" />
        <div className="skeleton sk-card" />
        <div className="skeleton sk-card" />
      </div>
      <div className="skeleton sk-chart" />
    </div>
  );
}
