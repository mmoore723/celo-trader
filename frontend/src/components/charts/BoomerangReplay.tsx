/**
 * BoomerangReplay.tsx — the "boomerang" scrub/replay UI: jumps back 15
 * candles before a setup, plays forward through it, and continues a bit
 * past the exit so you see how it resolved — instead of the old behavior of
 * showing the whole (over-zoomed-out) day at once.
 *
 * Two modes:
 *   "live"       — LiveTrading's "Watch this setup". Bars keep arriving from
 *                  the live poll; auto-follows to the live edge unless the
 *                  user has scrubbed back manually. Narration is synced from
 *                  timestamped bot trade-events as playback passes them.
 *   "historical" — Journal's "View on Chart" replay of an already-closed
 *                  trade. No live edge to chase; playback auto-stops a few
 *                  bars past the trade's exit instead of running to the end
 *                  of the fetched window. Narration is the trade's existing
 *                  one-line `recap` field, shown for the whole replay.
 */
import { useEffect, useImperativeHandle, useRef, useState, forwardRef } from "react";
import { Play, Pause, SkipForward } from "lucide-react";
import { TradeChart, type TradeChartProps } from "./TradeChart";

const SPEEDS = [1, 2, 4, 8] as const;
const LEAD_IN_BARS = 15;      // candles of context shown before entry
const TAIL_BARS = 8;          // candles played past the exit before stopping (historical mode)

export interface NarrationEvent { ts: string; message: string }

export interface BoomerangReplayHandle {
  /** Jump to `isoTime`, landing 15 bars before it, and start playing. */
  jumpToTime: (isoTime: string, stopAtIso?: string) => void;
}

interface Props extends TradeChartProps {
  mode?: "live" | "historical";
  /** Changes whenever the underlying data means any in-progress scrub position is meaningless
   *  (e.g. `${ticker}|${tf}` on LiveTrading) — triggers a reset to the live/full view. */
  resetKey?: string;
  narrationEvents?: NarrationEvent[];   // live mode: timestamped, synced to playhead
  staticNarration?: string;             // historical mode: one recap, shown throughout
}

export const BoomerangReplay = forwardRef<BoomerangReplayHandle, Props>(function BoomerangReplay(
  { bars, mode = "live", resetKey, narrationEvents, staticNarration, ...rest }, ref,
) {
  const [idx, setIdx] = useState(bars.length);
  const [playing, setPlaying] = useState(false);
  const [speedIdx, setSpeedIdx] = useState(0);
  const [stopAtIdx, setStopAtIdx] = useState<number | null>(null);
  const wasAtLive = useRef(true);
  const prevResetKey = useRef(resetKey);

  // Live mode only: new bars arriving shouldn't yank a mid-scrub view back —
  // only auto-advance if the user was already caught up.
  useEffect(() => {
    if (mode === "live" && wasAtLive.current) setIdx(bars.length);
  }, [bars.length, mode]);

  // Ticker/timeframe (or whatever resetKey represents) changed — old scrub
  // position is meaningless for a different bars array, always reset.
  useEffect(() => {
    if (resetKey !== prevResetKey.current) {
      prevResetKey.current = resetKey;
      wasAtLive.current = true;
      setPlaying(false);
      setStopAtIdx(null);
      setIdx(bars.length);
    }
  }, [resetKey, bars.length]);

  useEffect(() => {
    if (!playing) return;
    const ceiling = stopAtIdx != null ? Math.min(stopAtIdx, bars.length) : bars.length;
    if (idx >= ceiling) { setPlaying(false); return; }
    const t = setTimeout(() => setIdx((i) => Math.min(i + 1, ceiling)), Math.max(120, 500 / SPEEDS[speedIdx]));
    return () => clearTimeout(t);
  }, [playing, idx, bars.length, speedIdx, stopAtIdx]);

  useImperativeHandle(ref, () => ({
    jumpToTime(isoTime: string, stopAtIso?: string) {
      if (bars.length === 0) return;
      let landIdx = bars.findIndex((b) => new Date(b.time).getTime() >= new Date(isoTime).getTime());
      if (landIdx === -1) landIdx = bars.length;
      landIdx = Math.max(1, landIdx - LEAD_IN_BARS);

      let stop: number | null = null;
      if (stopAtIso) {
        let exitIdx = bars.findIndex((b) => new Date(b.time).getTime() >= new Date(stopAtIso).getTime());
        if (exitIdx === -1) exitIdx = bars.length;
        stop = Math.min(bars.length, exitIdx + TAIL_BARS);
      }

      wasAtLive.current = false;
      setStopAtIdx(stop);
      setIdx(landIdx);
      setPlaying(true);
    },
  }), [bars]);

  const atLive = mode === "live" && idx >= bars.length && stopAtIdx == null;
  const cutoffBar = bars[Math.max(0, idx - 1)];

  function goLive() {
    wasAtLive.current = true;
    setStopAtIdx(null);
    setIdx(bars.length);
    setPlaying(false);
  }
  function onScrub(v: number) {
    wasAtLive.current = mode === "live" && v >= bars.length;
    setIdx(v);
    setPlaying(false);
  }

  // Narration: live mode syncs to the most recent event at-or-before the
  // current playhead time; historical mode just shows the static recap.
  const narrationText = (() => {
    if (mode === "historical") return staticNarration ?? null;
    if (!narrationEvents?.length || !cutoffBar) return null;
    const cutoffMs = new Date(cutoffBar.time).getTime();
    let best: NarrationEvent | null = null;
    for (const ev of narrationEvents) {
      const t = new Date(ev.ts).getTime();
      if (t <= cutoffMs && (!best || t > new Date(best.ts).getTime())) best = ev;
    }
    return best?.message ?? null;
  })();

  return (
    <div className="flex flex-col w-full">
      <TradeChart bars={bars} revealCount={idx} {...rest} />

      {narrationText && (
        <div className="px-3 py-1.5 text-[12px] italic border-t" style={{ borderColor: "var(--border)", background: "var(--surface)", color: "var(--ink-muted)" }}>
          {narrationText}
        </div>
      )}

      {bars.length > 5 && (
        <div className="flex items-center gap-2 px-3 py-1.5 border-t text-[11px]" style={{ borderColor: "var(--border)", background: "var(--surface)" }}>
          <button className="btn btn-ghost btn-sm" title={playing ? "Pause" : "Play"} onClick={() => setPlaying((p) => !p)}>
            {playing ? <Pause size={13} /> : <Play size={13} />}
          </button>
          <input type="range" min={1} max={bars.length} value={idx} onChange={(e) => onScrub(Number(e.target.value))} style={{ flex: 1, accentColor: "var(--accent)" }} />
          <span style={{ color: "var(--ink-muted)", minWidth: 62, textAlign: "right", fontFamily: "monospace" }}>
            {atLive ? "● LIVE" : new Date(cutoffBar?.time ?? 0).toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" })}
          </span>
          <div className="flex gap-0.5">
            {SPEEDS.map((s, i) => (
              <button key={s} className={`btn btn-sm ${speedIdx === i ? "btn-primary" : "btn-ghost"}`} style={{ padding: "1px 6px", fontSize: 10 }} onClick={() => setSpeedIdx(i)}>{s}×</button>
            ))}
          </div>
          {mode === "live" && !atLive && (
            <button className="btn btn-ghost btn-sm" title="Jump to live" onClick={goLive}><SkipForward size={13} /></button>
          )}
        </div>
      )}
    </div>
  );
});
