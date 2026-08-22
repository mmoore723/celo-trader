import { Check, ChevronLeft, ChevronRight, RotateCcw, Sparkles } from "lucide-react";
import { useState } from "react";

type LessonStep = {
  title: string;
  label: string;
  explanation: string;
  watch: string[];
  avoid: string;
  focus: number;
};

const STEPS: LessonStep[] = [
  { title: "Find a real trend", label: "Trend", focus: 0, explanation: "Coach Celo starts with direction, not a prediction. The quick trend line needs to be above the slow trend line for a call idea, or below it for a put idea.", watch: ["Both trend lines pointing the same way", "Price staying on that side", "A completed 5-minute candle"], avoid: "Mixed, flat, crossing lines are chop. The right choice is to wait." },
  { title: "Wait for price to prove it", label: "Proof", focus: 1, explanation: "A trend is not enough. Price must close through its recent mini-range in the same direction. That is the bot's proof that the move is continuing, rather than simply bouncing around.", watch: ["Close beyond the recent high for calls", "Close below the recent low for puts", "The signal is based on a finished candle"], avoid: "Do not enter halfway through a candle. The close matters." },
  { title: "Enter on the next candle", label: "Entry", focus: 2, explanation: "Once the completed signal is valid, the bot checks the next available option quote. It does not look ahead at future price movement to make an entry look better. Observation records the decision without an order; an enabled trading strategy can send the order.", watch: ["Signal candle has finished", "Next bar is the entry opportunity", "Option spread is reasonable"], avoid: "Never assume a chart signal equals a fill at a perfect price." },
  { title: "Know where the idea is wrong", label: "Risk", focus: 3, explanation: "Every trend trade needs an invalidation line beyond the signal's structure. If price breaks that line, the trend idea did not hold. The bot exits rather than turning a trade into hope.", watch: ["The entry candle's structure", "A clear invalidation level", "Risk small enough for the account"], avoid: "Do not add contracts just because price moved against you." },
  { title: "Measure, then improve", label: "Review", focus: 4, explanation: "This exact TSLA strategy version is still being validated. It can shadow-observe in either a paper or live account without placing an order. We measure the real option ask at entry and bid at exit over 90 minutes, then compare which visible chart conditions survive later data. After qualification, each user can choose a one-contract pilot without changing account mode.", watch: ["Observed option bid and ask", "Earlier data versus later holdout data", "Whether the rule stays positive later"], avoid: "A few winners do not prove a strategy. We need repeatable evidence and the user's approval before a new live pilot." },
];

function TrendChart({ focus }: { focus: number }) {
  const candles = [
    [62, 156, 142], [90, 144, 151], [118, 152, 135], [146, 136, 128], [174, 130, 119],
    [202, 120, 108], [230, 110, 116], [258, 118, 99], [286, 101, 86], [314, 88, 92],
    [342, 94, 72], [370, 74, 60], [398, 63, 68], [426, 70, 50], [454, 52, 42],
  ];
  const marker = [150, 258, 342, 400, 470][focus];
  return <div className="rounded-xl p-3" style={{ background: "linear-gradient(150deg, var(--muted), color-mix(in srgb, var(--accent) 8%, var(--muted)))", border: "1px solid var(--border)" }}>
    <div className="flex justify-between text-xs font-semibold mb-2" style={{ color: "var(--ink)" }}><span>TSLA · 5-minute trend replay</span><span style={{ color: "var(--ink-muted)" }}>Practice chart</span></div>
    <svg viewBox="0 0 560 220" className="w-full" role="img" aria-label="Illustrated TSLA trend continuation candlestick chart">
      {[35, 78, 121, 164].map((y) => <line key={y} x1="28" y1={y} x2="535" y2={y} stroke="var(--border)" />)}
      <rect x={marker - 28} y="20" width="70" height="155" rx="8" fill="color-mix(in srgb, var(--accent) 10%, transparent)" stroke="var(--accent)" strokeDasharray="4 4" />
      <path d="M34 162 C100 154 137 139 194 121 S286 93 348 70 S433 50 518 38" fill="none" stroke="#df911f" strokeWidth="2.5" />
      <path d="M34 174 C104 168 145 151 200 135 S292 108 350 87 S437 65 518 51" fill="none" stroke="#8359d5" strokeWidth="2.5" />
      {candles.map(([x, open, close], index) => { const up = close < open; const color = up ? "var(--positive)" : "var(--negative)"; return <g key={x} opacity={index < 5 ? .72 : 1}><line x1={x + 7} x2={x + 7} y1={Math.min(open, close) - 10} y2={Math.max(open, close) + 10} stroke={color} /><rect x={x} y={Math.min(open, close)} width="14" height={Math.max(5, Math.abs(open - close))} rx="1" fill={color} /></g>; })}
      <text x="397" y="86" fontSize="10" fill="#df911f">Fast trend</text><text x="397" y="102" fontSize="10" fill="#8359d5">Slow trend</text><text x={marker - 20} y="35" fontSize="10" fill="var(--accent)" fontWeight="600">Current lesson</text>
      <text x="30" y="202" fontSize="10" fill="var(--ink-muted)">10:30</text><text x="174" y="202" fontSize="10" fill="var(--ink-muted)">11:00</text><text x="318" y="202" fontSize="10" fill="var(--ink-muted)">11:30</text><text x="462" y="202" fontSize="10" fill="var(--ink-muted)">12:00</text>
    </svg>
  </div>;
}

export function TrendCoachLesson() {
  const [step, setStep] = useState(0);
  const current = STEPS[step];
  const go = (next: number) => setStep(Math.max(0, Math.min(next, STEPS.length - 1)));
  return <section className="card overflow-hidden">
    <div className="p-4 sm:p-5" style={{ background: "linear-gradient(125deg, color-mix(in srgb, var(--accent) 15%, var(--surface)), var(--surface) 62%)", borderBottom: "1px solid var(--border)" }}><div className="flex items-center gap-3"><img src="/images/coach-celo-v1.png" alt="Coach Celo" className="w-12 h-12 object-contain object-bottom" /><div><p className="text-[11px] uppercase tracking-[.16em] font-semibold" style={{ color: "var(--accent)" }}>Coach Celo · Learn by replay</p><h2 className="text-lg font-semibold" style={{ color: "var(--ink)" }}>TSLA Trend Continuation</h2><p className="text-xs" style={{ color: "var(--ink-muted)" }}>A strategy-validation lesson — not investment advice.</p></div></div></div>
    <div className="p-4 sm:p-5 grid gap-4" style={{ gridTemplateColumns: "minmax(0, 1.6fr) minmax(250px, .85fr)" }}><div className="flex flex-col gap-3"><TrendChart focus={current.focus} /><div className="flex items-center justify-between"><button className="btn btn-ghost btn-sm" disabled={!step} onClick={() => go(step - 1)}><ChevronLeft size={15} /> Back</button><span className="text-xs font-semibold" style={{ color: "var(--ink-muted)" }}>Step {step + 1} of {STEPS.length}</span><button className="btn btn-primary btn-sm" disabled={step === STEPS.length - 1} onClick={() => go(step + 1)}>Next <ChevronRight size={15} /></button></div><div className="grid gap-1.5" style={{ gridTemplateColumns: "repeat(5, minmax(0, 1fr))" }}>{STEPS.map((item, index) => <button key={item.label} onClick={() => go(index)} className="rounded-lg px-1.5 py-2 text-left text-[11px]" style={{ cursor: "pointer", border: index === step ? "1px solid var(--accent)" : "1px solid var(--border)", background: index === step ? "color-mix(in srgb, var(--accent) 12%, var(--surface))" : "var(--surface)", color: index === step ? "var(--accent)" : "var(--ink-muted)" }}><span className="font-semibold block">{index + 1}</span>{item.label}</button>)}</div></div><aside className="rounded-xl p-4 flex flex-col gap-4" style={{ background: "var(--muted)", border: "1px solid var(--border)" }}><div className="flex gap-2 text-xs font-semibold" style={{ color: "var(--accent)" }}><Sparkles size={14} /> Coach Celo</div><div><h3 className="text-base font-semibold" style={{ color: "var(--ink)" }}>{current.title}</h3><p className="text-sm leading-relaxed mt-2" style={{ color: "var(--ink-muted)" }}>{current.explanation}</p></div><div><p className="text-[11px] uppercase tracking-widest font-semibold mb-2" style={{ color: "var(--ink-muted)" }}>What to watch</p>{current.watch.map((item) => <div key={item} className="flex gap-2 text-xs mb-2" style={{ color: "var(--ink)" }}><Check size={14} className="shrink-0" style={{ color: "var(--positive)" }} />{item}</div>)}</div><div className="rounded-lg p-3 text-xs leading-relaxed" style={{ background: "var(--negative-bg)", color: "var(--ink-muted)", borderLeft: "3px solid var(--negative)" }}><strong style={{ color: "var(--ink)" }}>Avoid the chop:</strong> {current.avoid}</div><button className="btn btn-ghost btn-sm mt-auto self-start" onClick={() => go(0)}><RotateCcw size={13} /> Restart lesson</button></aside></div>
  </section>;
}
