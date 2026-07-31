/**
 * BrokerAlertBanner.tsx — Persistent red banner when a broker is failing.
 *
 * Added 2026-07-31 after a Tradier credential got accidentally overwritten
 * (a masked display value was saved over the real key — see the
 * credentials-save fix in Settings.tsx/api/routes/settings.py) and ran
 * silently for 7+ minutes, 268 failed calls across every ticker, with zero
 * visible indication anywhere except individual "no_option_data" journal
 * rows that look like normal signal noise one ticker at a time. This reads
 * BotStatus.broker_alerts (populated from broker_health.py) and puts it
 * somewhere impossible to miss, on every page, until the broker recovers.
 */
import { useBotStore } from "../store/bot";

function timeAgo(epochSec: number): string {
  const mins = Math.max(0, Math.round((Date.now() / 1000 - epochSec) / 60));
  if (mins < 1) return "just now";
  if (mins === 1) return "1 min ago";
  return `${mins} min ago`;
}

export function BrokerAlertBanner() {
  const alerts = useBotStore((s) => s.status?.broker_alerts) ?? [];
  if (alerts.length === 0) return null;

  return (
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
          🔴 {a.broker.toUpperCase()} is failing — {a.error_count} errors in the last few
          minutes (since {timeAgo(a.since)}). The bot cannot trade on {a.broker} data right
          now. Check Settings → API Credentials.
        </span>
      ))}
    </div>
  );
}
