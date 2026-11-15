export function StrategyExitNotice() {
  return (
    <section className="rounded-lg p-3" aria-label="Strategy exit rules"
      style={{ background: "var(--surface-raised)", border: "1px solid var(--border)" }}>
      <h3 className="text-sm font-semibold mb-1" style={{ color: "var(--ink)" }}>Strategy exit rules</h3>
      <p className="text-xs" style={{ color: "var(--ink-muted)" }}>
        Open Strategies and choose a ticker to view or change its exit rules. Saved changes
        apply to new entries. Open positions keep their entry-time rules. Account risk
        and daily loss limits still apply.
      </p>
    </section>
  );
}
