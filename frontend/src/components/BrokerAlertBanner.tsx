/**
 * BrokerAlertBanner.tsx — Persistent red banner + one-time toast when a broker is failing.
 *
 * Added 2026-07-31 after a Tradier credential got accidentally overwritten
 * (a masked display value was saved over the real key — see the
 * credentials-save fix in Settings.tsx/api/routes/settings.py) and ran
 * silently for 7+ minutes, 268 failed calls across every ticker, with zero
 * visible indication anywhere except individual "no_option_data" journal
 * rows that look like normal signal noise one ticker at a time. This reads
 * BotStatus.broker_alerts (populated from broker_health.py) and puts it
 * somewhere impossible to miss, on every page, until the broker recovers.
 *
 * Toast added same day, per explicit request: the banner alone is easy to
 * miss if you're not looking at the top of the page. Fires once per
 * incident (keyed on broker + "since" timestamp — a fresh "since" means the
 * previous incident cleared and a new one started, so it fires again),
 * auto-dismisses after 20s, and can be closed early. The banner itself
 * still stays up the whole time the broker is unhealthy — this is on top
 * of it, not instead of it.
 */
import { useEffect, useState } from "react";
import { useBotStore } from "../store/bot";

type BrokerAlert = { broker: string; error_count: number; since: number; last_error: string };

export function BrokerAlertBanner() {
  const alerts = useBotStore((s) => s.status?.broker_alerts) ?? [];
  return (
    <>
      <BrokerAlertToasts alerts={alerts} />
      {alerts.length > 0 && (
        <div
          role="alert"
          style={{
            background: "#7f1d1d",
            color: "#fff",
            padding: "10px 16px",
            fontSize: 13,
            fontWeight: 600,
            display: "flex",
            flexWrap: "wrap",
            gap: "8px 20px",
            alignItems: "center",
            zIndex: 50,
            position: "relative",
          }}
        >
          {alerts.map((a) => (
            <span key={a.broker}>
              🔴 {a.broker.toUpperCase()} — {a.last_error || `${a.error_count} recent errors`}.
              {a.broker.includes("reconciliation")
                ? " Check Alpaca Order Flow and Reconcile in the Trade Journal."
                : ` The bot cannot trade on ${a.broker} data right now. Check Settings → API Credentials.`}
            </span>
          ))}
        </div>
      )}
    </>
  );
}

// ── Toast layer — fires once per new incident, sits top-right, self-dismisses ──
function BrokerAlertToasts({ alerts }: { alerts: BrokerAlert[] }) {
  // key = `${broker}:${since}` so a NEW "since" (broker recovered, then failed
  // again later) re-triggers the toast instead of staying silently suppressed.
  const [shown, setShown] = useState<Record<string, boolean>>({});
  const [active, setActive] = useState<BrokerAlert[]>([]);

  useEffect(() => {
    const fresh = alerts.filter((a) => !shown[`${a.broker}:${a.since}`]);
    if (fresh.length === 0) return;
    setShown((prev) => {
      const next = { ...prev };
      fresh.forEach((a) => { next[`${a.broker}:${a.since}`] = true; });
      return next;
    });
    setActive((prev) => [...prev, ...fresh]);
    fresh.forEach((a) => {
      const key = `${a.broker}:${a.since}`;
      setTimeout(() => {
        setActive((prev) => prev.filter((x) => `${x.broker}:${x.since}` !== key));
      }, 20_000);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [alerts]);

  if (active.length === 0) return null;

  return (
    <div
      style={{
        position: "fixed", top: 16, right: 16, zIndex: 200,
        display: "flex", flexDirection: "column", gap: 10, maxWidth: 360,
      }}
    >
      {active.map((a) => {
        const key = `${a.broker}:${a.since}`;
        return (
          <div
            key={key}
            role="alert"
            style={{
              background: "#7f1d1d", color: "#fff", borderRadius: 8,
              padding: "12px 14px", boxShadow: "0 4px 16px rgba(0,0,0,0.4)",
              fontSize: 13, display: "flex", gap: 10, alignItems: "flex-start",
            }}
          >
            <span style={{ flex: 1 }}>
              <strong>🔴 {a.broker.toUpperCase()}</strong><br />
              {a.last_error || `${a.error_count} failed calls.`}
              {a.broker.includes("reconciliation")
                ? " Check Trade Journal → Alpaca Order Flow/Reconcile."
                : ` The bot can't trade on ${a.broker} data. Check Settings → API Credentials.`}
            </span>
            <button
              onClick={() => setActive((prev) => prev.filter((x) => `${x.broker}:${x.since}` !== key))}
              aria-label="Dismiss"
              style={{
                background: "none", border: "none", color: "#fff", cursor: "pointer",
                fontSize: 16, lineHeight: 1, padding: 0, opacity: 0.8,
              }}
            >
              ×
            </button>
          </div>
        );
      })}
    </div>
  );
}
