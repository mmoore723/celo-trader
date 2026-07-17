/**
 * ChartReplay.tsx — Phase 3 of the chart refactor: a scrub-bar replay engine
 * wrapped around KChart.
 *
 * REDESIGNED 2026-07-19. The original version sliced `bars`/`trades` down to
 * the scrub position and re-fed the shorter arrays into KChart on every tick.
 * That re-triggered KChart's entire data-load effect (applyNewData + a
 * 150ms-delayed scroll/resize/overlay cycle) every tick, which is what caused
 * the candle pane and the RSI/MACD sub-panes to visibly show different time
 * ranges at once — confirmed from a screen recording, and NOT fixed by two
 * follow-up patches (a ticker/tf reset guard, then flooring the tick interval
 * at 300ms), because neither patch touched the actual cause: repeated
 * whole-array re-feeds.
 *
 * This version never slices anything. KChart always receives the full,
 * stable `bars`/`trades` arrays — so its heavy data-load effect only runs
 * when the real data changes (ticker/tf switch, new bars arriving), never on
 * a replay tick. Replay position is instead passed down as `revealUntil`
 * (an epoch-ms cutoff); KChart itself masks everything after that point on
 * every pane and does a cheap viewport nudge — see the `revealUntil` effect
 * in KChart.tsx. Since RSI/MACD/VOL are computed once against the full,
 * unchanging dataset, they can no longer fall out of sync with the candle
 * pane the way they did before.
 */
import { useEffect, useRef, useState, useImperativeHandle, forwardRef } from "react";
import { Play, Pause, SkipForward } from "lucide-react";
import { KChart, type KChartProps } from "./KChart";

const SPEEDS = [1, 2, 4, 8] as const;

export interface ChartReplayHandle {
  /** Jump the scrub position to just before `isoTime` and start playing. */
  jumpToTime: (isoTime: string) => void;
}

type Props = KChartProps;

export const ChartReplay = forwardRef<ChartReplayHandle, Props>(function ChartReplay(
  { bars, trades = [], ticker, tf, ...rest },
  ref
) {
  // idx === bars.length means "caught up to live" — the normal, default state.
  // Anything less is a replay position (how many bars are revealed so far).
  const [idx, setIdx]       = useState(bars.length);
  const [playing, setPlay]  = useState(false);
  const [speedIdx, setSpeedIdx] = useState(0);
  const wasAtLive = useRef(true);

  // When new bars arrive (live refetch), only auto-advance the cutoff if the
  // user was already caught up to live — otherwise a mid-replay scrub would
  // keep getting yanked back to the end every 30s refetch.
  useEffect(() => {
    if (wasAtLive.current) setIdx(bars.length);
  }, [bars.length]);

  // Switching ticker or timeframe means `idx` was meaningful for a totally
  // different bars array — always jump to live rather than keep a stale,
  // now-meaningless index (this was the cause of TF/ticker buttons looking
  // unresponsive mid-replay).
  const prevKey = useRef(`${ticker}|${tf}`);
  useEffect(() => {
    const key = `${ticker}|${tf}`;
    if (key !== prevKey.current) {
      prevKey.current = key;
      wasAtLive.current = true;
      setPlay(false);
      setIdx(bars.length);
    }
  }, [ticker, tf, bars.length]);

  // Playback tick — steps one bar forward per interval. No longer needs to be
  // throttled to protect chart redraw timing (that redraw no longer happens
  // per-tick at all — see file header), so this floor is just for
  // human-watchable pacing.
  useEffect(() => {
    if (!playing) return;
    if (idx >= bars.length) { setPlay(false); return; }
    const t = setTimeout(() => setIdx((i) => Math.min(i + 1, bars.length)),
                          Math.max(120, 500 / SPEEDS[speedIdx]));
    return () => clearTimeout(t);
  }, [playing, idx, bars.length, speedIdx]);

  useImperativeHandle(ref, () => ({
    jumpToTime(isoTime: string) {
      const target = new Date(isoTime).getTime();
      if (Number.isNaN(target) || bars.length === 0) return;
      // Land a few bars BEFORE the signal so there's context leading into it,
      // not a chart that starts exactly at the moment of interest.
      let landIdx = bars.findIndex((b) => new Date(b.time).getTime() >= target);
      if (landIdx === -1) landIdx = bars.length;
      landIdx = Math.max(1, landIdx - 3);
      wasAtLive.current = false;
      setIdx(landIdx);
      setPlay(true);
    },
  }), [bars]);

  const atLive = idx >= bars.length;
  const cutoffBar = bars[Math.max(0, idx - 1)];
  // Epoch-ms cutoff handed to KChart. undefined = normal live view (no mask).
  // Trade-marker filtering and the future mask are both computed inside
  // KChart from this one value — nothing gets sliced here anymore.
  const revealUntil = atLive || !cutoffBar ? undefined : new Date(cutoffBar.time).getTime();

  function goLive() {
    wasAtLive.current = true;
    setIdx(bars.length);
    setPlay(false);
  }

  function onScrub(v: number) {
    wasAtLive.current = v >= bars.length;
    setIdx(v);
    setPlay(false);
  }

  return (
    <div className="flex flex-col w-full">
      <KChart bars={bars} trades={trades} ticker={ticker} tf={tf} revealUntil={revealUntil} {...rest} />

      {/* Scrub bar — only meaningful once there's more than a handful of bars */}
      {bars.length > 5 && (
        <div
          className="flex items-center gap-2 px-3 py-1.5 border-t text-[11px]"
          style={{ borderColor: "var(--border)", background: "var(--surface)" }}
        >
          <button
            className="btn btn-ghost btn-sm"
            title={playing ? "Pause" : "Play"}
            onClick={() => setPlay((p) => !p)}
          >
            {playing ? <Pause size={13} /> : <Play size={13} />}
          </button>
          <input
            type="range"
            min={1}
            max={bars.length}
            value={idx}
            onChange={(e) => onScrub(Number(e.target.value))}
            style={{ flex: 1, accentColor: "var(--accent)" }}
          />
          <span style={{ color: "var(--ink-muted)", minWidth: 62, textAlign: "right", fontFamily: "monospace" }}>
            {atLive
              ? "● LIVE"
              : new Date(cutoffBar?.time ?? 0).toLocaleTimeString("en-US",
                  { hour: "numeric", minute: "2-digit" })}
          </span>
          <div className="flex gap-0.5">
            {SPEEDS.map((s, i) => (
              <button
                key={s}
                className={`btn btn-sm ${speedIdx === i ? "btn-primary" : "btn-ghost"}`}
                style={{ padding: "1px 6px", fontSize: 10 }}
                onClick={() => setSpeedIdx(i)}
              >
                {s}×
              </button>
            ))}
          </div>
          {!atLive && (
            <button className="btn btn-ghost btn-sm" title="Jump to live" onClick={goLive}>
              <SkipForward size={13} />
            </button>
          )}
        </div>
      )}
    </div>
  );
});
