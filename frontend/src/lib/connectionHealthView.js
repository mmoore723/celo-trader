// Current health is independent of historical log severity. A failed refresh
// must not leave an old green result looking like a fresh connection check.
export function connectionHealthView(health, { failed = false, now = Date.now() } = {}) {
  const checked = Date.parse(health?.checked_at ?? "");
  const stale = !Number.isFinite(checked) || now - checked > 120_000 || checked > now + 5_000;
  const verified = Boolean(health) && !failed && !stale;
  const connections = (health?.connections ?? []).filter(row => row.required || row.status !== "not_used");
  return {
    verified,
    hasIssue: verified && (!health.ready || connections.some(row => row.required && row.status !== "connected")),
    checkedAt: Number.isFinite(checked) ? new Date(checked).toISOString() : null,
    connections,
  };
}

export function needsTradierSandbox(provider, paper) {
  return provider === "tradier" && paper === true;
}
