import { useEffect, useMemo, useState } from "react";
import { ChevronLeft, ChevronRight, Pause, Play, RotateCcw } from "lucide-react";

import coachCelo from "../../assets/learning/coach-celo-pointing.png";
import type { Bar, ChartAnnotation } from "../../lib/api";
import { TradeChart } from "../charts/TradeChart";

interface VisualEpisode {
  example_id: string; ticker: string; bars: Bar[]; decision_bar_index: number;
  direction?: string; category?: string; directional_move_pct?: number | null;
}

interface TeachingStep {
  id: string; title: string; narration: string; candle: number;
  price?: number; annotation?: ChartAnnotation; reveal?: number;
}

function lessonSteps(example: VisualEpisode, unlocked: boolean): TeachingStep[] {
  const decision = Math.min(example.decision_bar_index, example.bars.length - 1);
  const evidence = example.bars.slice(Math.max(0, decision - 24), decision + 1);
  if (!evidence.length) return [];
  const resistance = evidence.reduce((best, bar) => bar.high > best.high ? bar : best);
  const support = evidence.reduce((best, bar) => bar.low < best.low ? bar : best);
  const resistanceIndex = example.bars.indexOf(resistance);
  const supportIndex = example.bars.indexOf(support);
  const base: TeachingStep[] = [
    { id: "orient", title: "Read left to right", narration: "First, ignore the outcome. We only use candles that were complete at the decision.", candle: Math.max(0, decision - 12) },
    { id: "resistance", title: "Mark resistance", narration: `This completed swing high near ${resistance.high.toFixed(2)} is where buyers previously stalled.`, candle: resistanceIndex, price: resistance.high,
      annotation: { id: "lesson-resistance", type: "hline", strategy: "LEARNING", label: "Resistance", ts: resistance.time, price: resistance.high, color: "#ef4444" } },
    { id: "support", title: "Mark support", narration: `This completed swing low near ${support.low.toFixed(2)} is the nearby support reference.`, candle: supportIndex, price: support.low,
      annotation: { id: "lesson-support", type: "hline", strategy: "LEARNING", label: "Support", ts: support.time, price: support.low, color: "#22c55e" } },
    { id: "decision", title: "Freeze the decision", narration: "Now look at the final completed candle. Decide from its location relative to those levels—not from what happens next.", candle: decision, price: example.bars[decision].close,
      annotation: { id: "lesson-decision", type: "marker", strategy: "LEARNING", label: "Decide here", ts: example.bars[decision].time, price: example.bars[decision].close, color: "#60a5fa" } },
  ];
  if (unlocked) base.push({ id: "outcome", title: "Replay the evidence", narration: example.directional_move_pct == null
    ? "The outcome is unresolved, so we stop without inventing certainty."
    : `The recorded 60-minute underlying follow-through was ${example.directional_move_pct >= 0 ? "+" : ""}${example.directional_move_pct.toFixed(2)}%. Compare the path with your original decision.`,
    candle: example.bars.length - 1, price: example.bars[example.bars.length - 1]?.close, reveal: example.bars.length });
  return base;
}

export function VisualLessonStage({ example, unlocked = false }: { example: VisualEpisode; unlocked?: boolean }) {
  const steps = useMemo(() => lessonSteps(example, unlocked), [example, unlocked]);
  const [stepIndex, setStepIndex] = useState(0);
  const [playing, setPlaying] = useState(true);
  useEffect(() => { setStepIndex(0); setPlaying(true); }, [example.example_id, unlocked]);
  useEffect(() => {
    if (!playing || steps.length < 2) return;
    const timer = window.setInterval(() => setStepIndex((value) => value >= steps.length - 1 ? 0 : value + 1), 5200);
    return () => window.clearInterval(timer);
  }, [playing, steps.length]);
  const step = steps[Math.min(stepIndex, Math.max(0, steps.length - 1))];
  if (!step) return null;
  const decisionReveal = Math.min(example.bars.length, example.decision_bar_index + 1);
  const reveal = step.reveal ?? decisionReveal;
  const visible = example.bars.slice(0, reveal);
  const rangeHigh = Math.max(...visible.map((bar) => bar.high));
  const rangeLow = Math.min(...visible.map((bar) => bar.low));
  const x = 7 + 86 * step.candle / Math.max(1, visible.length - 1);
  const y = step.price == null ? 48 : 12 + 72 * (rangeHigh - step.price) / Math.max(0.0001, rangeHigh - rangeLow);
  const annotations = steps.slice(0, stepIndex + 1).flatMap((item) => item.annotation ? [item.annotation] : []);
  return <div className="card overflow-hidden">
    <style>{`@keyframes celo-walk{0%{transform:translateY(0)}50%{transform:translateY(-5px)}100%{transform:translateY(0)}} @keyframes lesson-pulse{0%,100%{transform:scale(.8);opacity:.45}50%{transform:scale(1.18);opacity:1}}`}</style>
    <div className="relative" style={{ minHeight: 480, background: "var(--surface)" }}>
      <TradeChart bars={example.bars} ticker={example.ticker} annotations={annotations} revealCount={reveal} viewportKey={`lesson:${example.example_id}`} showStructure showSwings showRsi={false} showMacd={false} height={480} />
      <div aria-hidden className="absolute rounded-full pointer-events-none" style={{ left: `${x}%`, top: `${y}%`, width: 34, height: 34, margin: -17, border: "3px solid #facc15", background: "rgba(250,204,21,.18)", boxShadow: "0 0 0 10px rgba(250,204,21,.08)", animation: "lesson-pulse 1.5s ease-in-out infinite" }} />
      <div className="absolute pointer-events-none transition-all duration-1000 ease-in-out" style={{ left: `clamp(4px, calc(${x}% + 20px), calc(100% - 150px))`, bottom: 4, animation: "celo-walk .7s ease-in-out infinite" }}>
        <img src={coachCelo} alt="" className="object-contain object-bottom drop-shadow-2xl" style={{ width: 145, height: 230 }} />
      </div>
      <div className="absolute left-3 top-3 max-w-[360px] rounded-xl p-3 shadow-xl" style={{ background: "color-mix(in srgb, var(--surface) 94%, transparent)", border: "1px solid var(--border)" }}>
        <p className="text-[10px] uppercase tracking-[.16em] font-bold" style={{ color: "var(--accent)" }}>Coach Celo · {stepIndex + 1}/{steps.length}</p>
        <p className="font-semibold mt-1" style={{ color: "var(--ink)" }}>{step.title}</p>
        <p className="text-sm mt-1 leading-relaxed" style={{ color: "var(--ink-muted)" }}>{step.narration}</p>
      </div>
    </div>
    <div className="p-3 flex items-center gap-2" style={{ borderTop: "1px solid var(--border)" }}>
      <button className="btn btn-sm btn-ghost" aria-label="Previous teaching step" onClick={() => setStepIndex((value) => (value - 1 + steps.length) % steps.length)}><ChevronLeft size={15} /></button>
      <button className="btn btn-sm btn-primary" onClick={() => setPlaying((value) => !value)}>{playing ? <Pause size={14} /> : <Play size={14} />}{playing ? "Pause teacher" : "Continue lesson"}</button>
      <button className="btn btn-sm btn-ghost" aria-label="Next teaching step" onClick={() => setStepIndex((value) => (value + 1) % steps.length)}><ChevronRight size={15} /></button>
      <button className="btn btn-sm btn-ghost ml-auto" onClick={() => { setStepIndex(0); setPlaying(false); }}><RotateCcw size={14} />Restart</button>
    </div>
  </div>;
}
