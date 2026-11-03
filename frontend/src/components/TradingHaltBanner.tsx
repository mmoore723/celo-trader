import { useState } from "react";
import { useTradingHalt } from "../hooks/useTradingHalt";

const base = import.meta.env.VITE_API_URL ?? "";

export function TradingHaltBanner() {
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const halt = useTradingHalt();
  async function resume() {
    if (!window.confirm("Resume new entries? Your existing daily loss limits will still apply. This does not reset your loss allowance.")) return;
    setBusy(true);
    try {
      const response = await fetch(`${base}/api/bot/halt/resume`, {
        method: "POST", credentials: "include", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ scope: halt.data?.scope }),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail || "Resume request failed. Halt remains unchanged.");
      setMessage(result.ok === true ? result.message : `Still halted: ${result.message || "Broker review did not approve resuming."}`);
      await halt.refetch();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Resume failed.");
    } finally { setBusy(false); }
  }
  if (!halt.data?.halted && !halt.isError) return message ? <div role="status" className="p-3">{message}</div> : null;
  return <section role="alert" aria-live="assertive" className="bg-red-900 text-white p-4 flex flex-wrap items-center gap-3">
    <div className="flex-1 min-w-0 basis-full sm:basis-64">
      <strong>{halt.isError ? "TRADING STATUS UNVERIFIED" : "TRADING HALTED: new entries blocked"}</strong>
      <p>{halt.isError ? "Cannot refresh halt status. Do not assume the bot is trading." : halt.data?.reason}</p>
      {halt.data?.close_pending && <p>Emergency exits are awaiting broker confirmation. Resume is unavailable until they finish.</p>}
      <p role="status">{message || "Resume checks the broker and your existing loss limits. It cannot override a breached limit."}</p>
    </div>
    <button className="border rounded px-3 py-2" onClick={() => setMessage("Kept halted. No settings or limits changed.")}>Keep halted</button>
    <button className="bg-white text-red-900 rounded px-3 py-2 disabled:opacity-50" disabled={busy || halt.isError || halt.data?.close_pending} onClick={resume}>{busy ? "Checking broker..." : "Resume trading"}</button>
  </section>;
}
