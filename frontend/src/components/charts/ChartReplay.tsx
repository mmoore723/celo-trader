/**
 * ChartReplay.tsx — Phase 3 of the chart refactor: a scrub-bar replay engine
 * wrapped around KChart.
 *
 * Two modes the user explicitly asked for ("Both"):
 *   1. Manual scrub — drag the slider or hit Play to step bar-by-bar through
 *      the loaded history at 1x/2x/4x/8x speed, watching candles/markers/
 *      the R:R bracket reveal progressively instead of seeing the whole day
 *      dumped on screen at once.
 *   2. "Watch this setup" — jumpToTime() snaps the scrub position to just
 *      before a specific signal's timestamp and starts auto-playing from
 *      there, so a single signal from the log can be replayed in isolation.
 *
 * How it works: KChart itself doesn't know about replay — this component
 * just slices `bars` (and any `trades` whose entry lands after the visible
 * cutoff) down to the current scrub position before handing them to KChart,
 * exactly the same props KChart already accepts. No changes needed inside
 * KChart for this to work.
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
  // Anything less is a replay position.
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

  // FIX 2026-07-17: switching ticker or timeframe used to leave `idx` at
  // whatever it was mid-replay. A scrub position from the PREVIOUS bars
  // array (different ticker/tf = different length and meaning entirely)
  // doesn't carry over meaningfully — the visible result was the TF/ticker
  // buttons looking like they'd stopped responding (confirmed from the
  // recording: clicking 1m/5m/15m/1h did nothing until navigating away and
  // back, which just force-remounts this component and resets its state).
  // Always jump to live on ticker/tf change instead of silently keeping a
  // stale, now-meaningless index.
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

  // Playback tick — steps one bar forward per interval, interval shrinks as
  // speed increases, floored at 300ms. FIX 2026-07-17: at 4x/8x the old
  // 500/speed formula pushed new data every 125ms/62.5ms — faster than
  // KChart's candle pane + built-in RSI/MACD indicator panes could redraw in
  // lockstep, so the panes visibly fell out of sync (confirmed from the
  // recording: candles frozen at one time range while RSI/MACD had already
  // moved on to a later one). The floor keeps every pane repainting together.
  useEffect(() => {
    if (!playing) return;
    if (idx >= bars.length) { setPlay(false); return; }
    const t = setTimeout(() => setIdx((i) => Math.min(i + 1, bars.length)),
                          Math.max(300, 500 / SPEEDS[speedIdx]));
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
  const visibleBars = bars.slice(0, Math.max(1, idx));
  const cutoffTs = visibleBars.length
    ? new Date(visibleBars[visibleBars.length - 1].time).getTime()
    : 0;
  // Trade markers/bracket only appear once the replay has reached that
  // trade's entry — keeps "watch it happen" honest instead of spoiling the
  // outcome before the scrub position gets there.
  const visibleTrades = atLive
    ? trades
    : trades.filter((t) => t.entry_time && new Date(t.entry_time).getTime() <= cutoffTs);

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
      <KChart bars={visibleBars} trades={visibleTrades} ticker={ticker} tf={tf} {...rest} />

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
              : new Date(visibleBars[visibleBars.length - 1]?.time ?? 0).toLocaleTimeString("en-US",
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
