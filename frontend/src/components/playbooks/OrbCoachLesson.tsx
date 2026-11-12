import { useMemo, useState } from "react";
import { Check, ChevronLeft, ChevronRight, RotateCcw, Sparkles } from "lucide-react";

type CoachBeat = {
  title: string;
  shortTitle: string;
  voice: string;
  coach: string;
  watch: string[];
  avoid: string;
  chartStage: "range" | "breakout" | "retest" | "confirm" | "exit";
  decision?: { prompt: string; choices: string[]; correct: number; explanation: string };
};

const ORB_BEATS: CoachBeat[] = [
  {
    title: "Build the opening range",
    shortTitle: "The first 15 minutes",
    voice: "Welcome to the TSLA Opening Range Pullback lesson. From 9:30 to 9:45, we do not trade. We simply mark the highest and lowest price from the first three five-minute candles. That box is the opening range. It gives us two clear levels to watch instead of guessing.",
    coach: "First we create a simple map. No trade yet.",
    watch: ["The high of the first three 5-minute candles", "The low of the first three 5-minute candles", "A clean chart — no prediction needed"],
    avoid: "Do not jump in during the first 15 minutes. Fast opening candles can be noisy.",
    chartStage: "range",
  },
  {
    title: "Wait for a real break",
    shortTitle: "The breakout",
    voice: "After 9:45, price must close outside the opening range. For a bullish setup, it closes above the range high. For a bearish setup, it closes below the range low. But a break is still not our entry. We do not chase the first move, because many early breakouts quickly turn back into the range.",
    coach: "A break gets our attention. It does not earn an entry.",
    watch: ["A completed 5-minute candle outside the range", "Whether price is breaking above or below", "Time: the break must happen before 10:30 ET"],
    avoid: "One wick outside the range is not enough. We use a candle close, not a quick poke.",
    chartStage: "breakout",
    decision: { prompt: "Price just closed above the range. What is the disciplined move?", choices: ["Buy a call immediately", "Wait for the pullback", "Ignore every breakout"], correct: 1, explanation: "Correct. This strategy is a pullback strategy. It waits for price to revisit the broken level instead of buying the first burst." },
  },
  {
    title: "Let price come back to you",
    shortTitle: "The pullback",
    voice: "Now we wait for the first pullback to the broken level. For a bullish setup, price comes back toward the opening range high. For a bearish setup, it comes back toward the opening range low. This is the bot's no-chase rule. If price never comes back, we let it go. Missing a trade is better than forcing a bad one.",
    coach: "The pullback is a test. Patience is the edge here.",
    watch: ["The first revisit of the broken range level", "Price respecting the opposite side of the range", "The pullback low or high — it becomes the invalidation level"],
    avoid: "If bullish price falls through the entire range, the setup is broken. Do not keep hoping.",
    chartStage: "retest",
    decision: { prompt: "The pullback touches the broken level but buyers have not returned. Trade, wait, or average down?", choices: ["Trade now", "Wait for proof", "Average down"], correct: 1, explanation: "Correct. A touch is not a bounce. The next completed candle must show that price reclaimed the level." },
  },
  {
    title: "Enter only after proof",
    shortTitle: "The confirmation",
    voice: "This is the entry check. For a bullish trade, the current candle must close back above the opening range high, above the prior candle's high, and above VWAP. For a bearish trade, the reverse must be true. Those three checks help the bot avoid choppy back-and-forth price action. It only gets one V2 opening-range pullback attempt per TSLA session, before 10:45 Eastern.",
    coach: "We want price to prove it has resumed — not merely look promising.",
    watch: ["Close back beyond the range boundary", "A break of the prior candle in the trade direction", "Price on the correct side of VWAP"],
    avoid: "If price keeps crossing the range boundary or VWAP back and forth, that is chop. The correct action is no trade.",
    chartStage: "confirm",
    decision: { prompt: "Which detail best tells us this is less likely to be chop?", choices: ["The option premium is cheap", "Price confirms beyond the level and VWAP", "A social-media alert"], correct: 1, explanation: "Correct. The bot uses the chart structure — not a cheap option or a headline — to decide whether there is a valid setup." },
  },
  {
    title: "Manage the trade without panic",
    shortTitle: "The exit plan",
    voice: "Before the option is selected, the trade has a clear invalidation level: the pullback low for a bullish trade, or the pullback high for a bearish trade. If price reaches that level, the original idea is wrong and the trade must exit. A normal small wiggle above a bullish pullback low is not automatically failure. The bot follows its defined exit rules rather than reacting to every tick. It also uses its risk and time rules so a trade does not become an all-day hope.",
    coach: "A planned exit protects the account. A panic exit does not.",
    watch: ["The pullback low or high that invalidates the setup", "Whether price still holds the intended side of the range", "The current account risk and time-exit rules"],
    avoid: "Do not widen a stop or add contracts because a trade is losing. A losing trade is information, not a reason to gamble.",
    chartStage: "exit",
    decision: { prompt: "Price loses the pullback low on a bullish trade. What does that tell us?", choices: ["The setup is invalid — exit by the rule", "Buy more to lower the average", "Wait forever for a rebound"], correct: 0, explanation: "Correct. The exit is not a punishment; it is proof that we protect a small account when the original idea is wrong." },
  },
];

// Version the image URL so a browser that cached the original failed request
// asks the server for the coach again after a deployment.
const COACH_IMAGE = "/images/coach-celo-v1.png?v=2";

function CoachChart({ stage }: { stage: CoachBeat["chartStage"] }) {
  const index = ["range", "breakout", "retest", "confirm", "exit"].indexOf(stage);
  const labels = ["Opening range", "Break", "Pullback", "Confirmation", "Exit plan"];
  const focus = [
    { x: 40, width: 142, label: "Watch only — build the range" },
    { x: 180, width: 80, label: "Breakout candle closes outside" },
    { x: 252, width: 98, label: "First pullback tests the level" },
    { x: 344, width: 94, label: "Confirmation above VWAP" },
    { x: 514, width: 110, label: "Manage the exit plan" },
  ][index];
  const candles = [
    { x: 62, open: 145, close: 126, high: 116, low: 156 }, { x: 86, open: 126, close: 143, high: 151, low: 119 },
    { x: 110, open: 143, close: 132, high: 149, low: 121 }, { x: 134, open: 132, close: 139, high: 146, low: 123 },
    { x: 158, open: 139, close: 127, high: 143, low: 117 }, { x: 182, open: 127, close: 100, high: 131, low: 94 },
    { x: 206, open: 100, close: 88, high: 106, low: 80 }, { x: 230, open: 88, close: 76, high: 94, low: 70 },
    { x: 254, open: 76, close: 97, high: 104, low: 72 }, { x: 278, open: 97, close: 122, high: 128, low: 90 },
    { x: 302, open: 122, close: 111, high: 130, low: 102 }, { x: 326, open: 111, close: 94, high: 116, low: 88 },
    { x: 350, open: 94, close: 75, high: 100, low: 67 }, { x: 374, open: 75, close: 59, high: 81, low: 52 },
    { x: 398, open: 59, close: 67, high: 76, low: 54 }, { x: 422, open: 67, close: 55, high: 72, low: 48 },
    { x: 446, open: 55, close: 46, high: 61, low: 40 }, { x: 470, open: 46, close: 51, high: 57, low: 38 },
    { x: 494, open: 51, close: 43, high: 58, low: 35 }, { x: 518, open: 43, close: 62, high: 67, low: 39 },
    { x: 542, open: 62, close: 75, high: 81, low: 56 }, { x: 566, open: 75, close: 68, high: 85, low: 63 },
  ];
  return (
    <div className="rounded-xl p-3" style={{ background: "linear-gradient(150deg, var(--muted), color-mix(in srgb, var(--accent) 8%, var(--muted)))", border: "1px solid var(--border)" }}>
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs font-semibold" style={{ color: "var(--ink)" }}>TSLA · 5-minute candle replay</span>
        <span className="text-[11px]" style={{ color: "var(--ink-muted)" }}>Illustrated practice chart</span>
      </div>
      <svg viewBox="0 0 660 260" className="w-full" role="img" aria-label="Illustrated candlestick opening-range pullback chart with the current lesson moment highlighted">
        {[40, 90, 140, 190].map((y) => <line key={y} x1="35" y1={y} x2="645" y2={y} stroke="var(--border)" strokeWidth="1" />)}
        <rect x={focus.x} y="25" width={focus.width} height="180" rx="8" fill="color-mix(in srgb, var(--accent) 10%, transparent)" stroke="var(--accent)" strokeWidth="1.5" strokeDasharray="4 4" />
        <rect x="42" y="104" width="144" height="55" rx="6" fill="color-mix(in srgb, var(--accent) 11%, transparent)" stroke="var(--accent)" strokeWidth={index === 0 ? 2 : 1} />
        <text x="49" y="98" fill="var(--ink-muted)" fontSize="11">Opening range</text>
        <line x1="35" y1="104" x2="645" y2="104" stroke="var(--accent)" strokeWidth="1.5" strokeDasharray="5 4" />
        {candles.map((candle, candleIndex) => {
          const up = candle.close < candle.open;
          const color = up ? "var(--positive)" : "var(--negative)";
          const bodyY = Math.min(candle.open, candle.close);
          const bodyHeight = Math.max(5, Math.abs(candle.close - candle.open));
          return <g key={candle.x} opacity={candleIndex >= 5 ? 1 : 0.82}>
            <line x1={candle.x + 7} x2={candle.x + 7} y1={candle.high} y2={candle.low} stroke={color} strokeWidth="1.5" />
            <rect x={candle.x} y={bodyY} width="14" height={bodyHeight} rx="1.5" fill={color} />
          </g>;
        })}
        <path d="M42 157 C126 157 187 147 246 126 S335 105 399 98 S531 77 606 65" fill="none" stroke="#df911f" strokeWidth="2" />
        <path d="M42 170 C120 163 181 150 244 134 S337 114 404 104 S538 84 606 76" fill="none" stroke="#8359d5" strokeWidth="2" />
        <text x={focus.x + 5} y="43" fill="var(--accent)" fontSize="10" fontWeight="600">{focus.label}</text>
        <circle cx={[105, 189, 267, 363, 558][index]} cy={[130, 99, 97, 72, 74][index]} r="7" fill="var(--accent)" stroke="var(--surface)" strokeWidth="2" />
        <text x="45" y="230" fill="var(--ink-muted)" fontSize="11">9:30</text><text x="175" y="230" fill="var(--ink-muted)" fontSize="11">9:45</text><text x="303" y="230" fill="var(--ink-muted)" fontSize="11">10:00</text><text x="434" y="230" fill="var(--ink-muted)" fontSize="11">10:15</text><text x="564" y="230" fill="var(--ink-muted)" fontSize="11">10:30</text>
        <text x="583" y="106" fill="#df911f" fontSize="11">VWAP</text><text x="582" y="123" fill="#8359d5" fontSize="11">Trend line</text>
      </svg>
      <div className="flex gap-1.5 flex-wrap mt-1">
        {labels.map((label, itemIndex) => <span key={label} className="text-[11px] px-2 py-1 rounded-full" style={{ background: itemIndex === index ? "var(--accent)" : "var(--surface)", color: itemIndex === index ? "white" : "var(--ink-muted)" }}>{itemIndex + 1}. {label}</span>)}
      </div>
    </div>
  );
}

export function OrbCoachLesson() {
  const [beatIndex, setBeatIndex] = useState(0);
  const [answer, setAnswer] = useState<number | null>(null);
  const [guidedReplayActive, setGuidedReplayActive] = useState(false);
  const beat = ORB_BEATS[beatIndex];

  const goToBeat = (index: number) => {
    setBeatIndex(Math.min(Math.max(index, 0), ORB_BEATS.length - 1));
    setAnswer(null);
  };

  const startGuidedReplay = () => {
    setGuidedReplayActive(true);
    goToBeat(0);
  };

  const answerCopy = useMemo(() => {
    if (!beat.decision || answer === null) return "Choose an answer to practice the habit before you see the next part.";
    return answer === beat.decision.correct ? beat.decision.explanation : `Not this time. ${beat.decision.explanation}`;
  }, [answer, beat.decision]);

  return (
    <section className="card overflow-hidden">
      <div className="p-4 sm:p-5" style={{ background: "linear-gradient(125deg, color-mix(in srgb, var(--accent) 15%, var(--surface)), var(--surface) 62%)", borderBottom: "1px solid var(--border)" }}>
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div className="flex gap-3 items-center">
            <div className="w-12 h-12 rounded-2xl overflow-hidden shrink-0" style={{ border: "2px solid color-mix(in srgb, var(--accent) 45%, var(--border))", background: "color-mix(in srgb, var(--accent) 10%, var(--surface))", boxShadow: "0 0 26px color-mix(in srgb, var(--accent) 28%, transparent)" }}><img src={COACH_IMAGE} alt="Coach Celo" className="w-full h-full object-contain object-bottom" /></div>
            <div><p className="text-[11px] uppercase tracking-[0.16em] font-semibold" style={{ color: "var(--accent)" }}>Coach Celo · Learn by replay</p><h2 className="text-lg font-semibold mt-0.5" style={{ color: "var(--ink)" }}>Opening-Range Pullback</h2><p className="text-xs mt-1" style={{ color: "var(--ink-muted)" }}>A step-by-step practice replay — not investment advice.</p></div>
          </div>
          <button type="button" className="btn btn-ghost btn-sm self-start sm:self-auto" onClick={startGuidedReplay} aria-pressed={guidedReplayActive} title="Restart the five-step guided lesson">
            <Sparkles size={13} />{guidedReplayActive ? "Guided replay active" : "Start guided replay"}
          </button>
        </div>
      </div>
      <div className="p-4 sm:p-5 grid gap-4" style={{ gridTemplateColumns: "minmax(0, 1.6fr) minmax(250px, .85fr)" }}>
        <div className="min-w-0 flex flex-col gap-3">
          <CoachChart stage={beat.chartStage} />
          <div className="flex items-center justify-between gap-2">
            <button className="btn btn-ghost btn-sm" disabled={beatIndex === 0} onClick={() => goToBeat(beatIndex - 1)}><ChevronLeft size={15} /> Back</button>
            <span className="text-xs font-semibold" style={{ color: "var(--ink-muted)" }}>Step {beatIndex + 1} of {ORB_BEATS.length}</span>
            <button className="btn btn-primary btn-sm" disabled={beatIndex === ORB_BEATS.length - 1} onClick={() => goToBeat(beatIndex + 1)}>Next <ChevronRight size={15} /></button>
          </div>
          <div className="grid gap-1.5" style={{ gridTemplateColumns: "repeat(5, minmax(0, 1fr))" }} aria-label="Choose a lesson step">
            {ORB_BEATS.map((item, index) => (
              <button key={item.shortTitle} onClick={() => goToBeat(index)} className="rounded-lg px-1.5 py-2 text-left text-[11px] leading-tight" style={{ cursor: "pointer", border: index === beatIndex ? "1px solid var(--accent)" : "1px solid var(--border)", background: index === beatIndex ? "color-mix(in srgb, var(--accent) 12%, var(--surface))" : "var(--surface)", color: index === beatIndex ? "var(--accent)" : "var(--ink-muted)" }}>
                <span className="font-semibold block">{index + 1}</span>{item.shortTitle}
              </button>
            ))}
          </div>
        </div>
        <aside className="rounded-xl p-4 flex flex-col gap-4" style={{ background: "var(--muted)", border: "1px solid var(--border)" }}>
          <div><div className="flex items-center gap-2 text-xs font-semibold" style={{ color: "var(--accent)" }}><Sparkles size={14} /> Coach Celo · Lesson {beatIndex + 1} of {ORB_BEATS.length}</div><div className="flex items-start gap-3 mt-2"><img src={COACH_IMAGE} alt="Coach Celo, the strategy instructor" className="w-16 h-24 object-contain object-bottom shrink-0" /><div><h3 className="text-base font-semibold" style={{ color: "var(--ink)" }}>{beat.title}</h3><p className="text-xs leading-relaxed mt-1" style={{ color: "var(--ink-muted)" }}>{beat.coach}</p></div></div><div className="rounded-lg p-3 mt-2 text-sm leading-relaxed" style={{ background: "var(--surface)", color: "var(--ink-muted)", borderLeft: "3px solid var(--accent)" }}><strong style={{ color: "var(--ink)" }}>Coach Celo says:</strong> {beat.voice}</div></div>
          <div><p className="text-[11px] uppercase tracking-widest font-semibold mb-2" style={{ color: "var(--ink-muted)" }}>What to watch</p><ul className="flex flex-col gap-2">{beat.watch.map((item) => <li key={item} className="flex gap-2 text-xs" style={{ color: "var(--ink)" }}><Check size={14} className="shrink-0 mt-0.5" style={{ color: "var(--positive)" }} />{item}</li>)}</ul></div>
          <div className="rounded-lg p-3 text-xs leading-relaxed" style={{ background: "var(--negative-bg)", color: "var(--ink-muted)", borderLeft: "3px solid var(--negative)" }}><strong style={{ color: "var(--ink)" }}>Avoid the chop:</strong> {beat.avoid}</div>
          <button className="btn btn-ghost btn-sm mt-auto self-start" onClick={() => goToBeat(0)}><RotateCcw size={13} /> Restart lesson</button>
        </aside>
      </div>
      {beat.decision && <div className="mx-4 sm:mx-5 mb-5 rounded-xl p-4" style={{ background: "var(--surface)", border: "1px solid var(--border)" }}>
        <p className="text-sm font-semibold" style={{ color: "var(--ink)" }}>Practice it: {beat.decision.prompt}</p>
        <div className="grid gap-2 mt-3" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(170px, 1fr))" }}>{beat.decision.choices.map((choice, index) => <button key={choice} className="btn text-left justify-start" onClick={() => setAnswer(index)} style={answer === index ? { borderColor: index === beat.decision!.correct ? "var(--positive)" : "var(--negative)", background: index === beat.decision!.correct ? "var(--positive-bg)" : "var(--negative-bg)" } : undefined}>{choice}</button>)}</div>
        <p className="text-xs mt-3 leading-relaxed" style={{ color: answer === beat.decision.correct ? "var(--positive)" : "var(--ink-muted)" }}>{answerCopy}</p>
      </div>}
    </section>
  );
}
