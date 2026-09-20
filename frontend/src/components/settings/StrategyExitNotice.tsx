export function StrategyExitNotice() {
  return (
    <section className="rounded-lg p-3" aria-label="Strategy exit rules"
      style={{ background: "var(--surface-raised)", border: "1px solid var(--border)" }}>
      <h3 className="text-sm font-semibold mb-1" style={{ color: "var(--ink)" }}>Strategy exit rules</h3>
      <p className="text-xs" style={{ color: "var(--ink-muted)" }}>
        Exits follow each strategy&apos;s tested version. Proposed changes are compared
        separately in research, not switched here. Your account risk and daily loss
        limits remain under your control.
      </p>
    </section>
  );
}
