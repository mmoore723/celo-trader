import { useRef, useState } from "react";
import { useTradingHalt } from "../hooks/useTradingHalt";

const base = import.meta.env.VITE_API_URL ?? "";

export function TradingHaltBanner() {
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const dialog = useRef<HTMLDialogElement>(null);
  const [override, setOverride] = useState(false);
  const [amount, setAmount] = useState("");
  const [review, setReview] = useState({ scope: "", session: "" });
  const halt = useTradingHalt();
  function openReview() {
    setOverride(false);
    setAmount("");
    setMessage("");
    setReview({ scope: halt.data?.scope ?? "", session: halt.data?.session ?? "" });
    dialog.current?.showModal();
  }
  async function resume() {
    if (override && (!Number.isFinite(Number(amount)) || Number(amount) <= 0)) {
      setMessage("Enter a positive total daily loss limit in dollars."); return;
    }
    setBusy(true);
    try {
      const response = await fetch(`${base}/api/bot/halt/resume`, {
        method: "POST", credentials: "include", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...review, ...(override ? { temporary_limit_usd: Number(amount) } : {}) }),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail || "Resume request failed. Halt remains unchanged.");
      setMessage(result.ok === true ? result.message : `Still halted: ${result.message || "Broker review did not approve resuming."}`);
      if (result.ok === true) dialog.current?.close();
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
      <p role="status">{message || "Resume trading lets you review your limits or set a temporary limit for today."}</p>
    </div>
    <button className="border rounded px-3 py-2" onClick={() => setMessage("Kept halted. No settings or limits changed.")}>Keep halted</button>
    <button className="bg-white text-red-900 rounded px-3 py-2 disabled:opacity-50" disabled={busy || halt.isError || halt.data?.close_pending} onClick={openReview}>{busy ? "Checking broker..." : "Resume trading"}</button>
    <dialog ref={dialog} aria-labelledby="resume-title" className="rounded-xl p-6 max-w-lg w-full bg-white text-slate-900 backdrop:bg-black/50" onCancel={event => { if (busy) event.preventDefault(); }}>
      <h2 id="resume-title" className="text-xl font-semibold mb-3">Resume trading</h2>
      {halt.data?.realized_loss_limit_usd != null && <p className="mb-3">Current daily limits: realized loss ${halt.data.realized_loss_limit_usd.toFixed(2)}; equity loss ${halt.data.equity_loss_limit_usd?.toFixed(2)}.</p>}
      <p className="mb-4">Choose your daily loss limit. Broker positions and pending orders must be reconciled before trading resumes.</p>
      <label className="block mb-3"><input type="radio" name="resume-limit" checked={!override} disabled={busy} onChange={() => setOverride(false)} /> Keep current limits</label>
      <label className="block mb-3"><input type="radio" name="resume-limit" checked={override} disabled={busy} onChange={() => setOverride(true)} /> Set temporary daily stop loss</label>
      {override && <div className="mb-4">
        <label htmlFor="daily-loss-limit" className="block font-semibold">Total loss allowed today ($)</label>
        <input id="daily-loss-limit" type="number" min="0.01" step="0.01" value={amount} disabled={busy} onChange={event => setAmount(event.target.value)} className="border rounded p-2 w-full text-slate-900" />
        <p className="text-sm mt-2">Includes losses already taken, not additional spending room. Applies to realized losses and equity loss from today's starting balance. Replaces both daily caps for this account and mode until midnight Eastern. Permanent limits, position exits and live-trading status do not change.</p>
      </div>}
      {message && <p role="status" className="mb-3 text-red-700">{message}</p>}
      <div className="flex gap-3 justify-end">
        <button className="border rounded px-3 py-2" disabled={busy} onClick={() => dialog.current?.close()}>Cancel</button>
        <button className="bg-blue-600 text-white rounded px-3 py-2" disabled={busy || halt.isError || halt.data?.close_pending} onClick={resume}>{busy ? "Checking broker..." : "Confirm and resume"}</button>
      </div>
    </dialog>
  </section>;
}
