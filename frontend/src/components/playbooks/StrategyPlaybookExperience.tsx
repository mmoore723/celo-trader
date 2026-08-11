import { useEffect, useState } from "react";
import {
  Check, ChevronLeft, ChevronRight, Pause, Play, RotateCcw, ShieldCheck,
  Volume2,
} from "lucide-react";

type LessonId = "v2_orb" | "v2_trend";
type LessonStep = {
  label: string;
  title: string;
  lesson: string;
  coach: string;
  watch: string[];
  avoid: string;
  chartFocus: number;
  question: string;
  answers: string[];
  correct: number;
  answerWhy: string;
};
type Course = {
  id: LessonId;
  title: string;
  shortTitle: string;
  level: string;
  description: string;
  steps: LessonStep[];
};

const COACH_IMAGE = "/images/coach-celo-v1.png?v=3";

const COURSES: Course[] = [
  {
    id: "v2_orb",
    title: "TSLA Opening-Range Pullback",
    shortTitle: "Opening-Range Pullback",
    level: "Beginner · 5 steps",
    description: "A patient setup: let price break the opening range, pull back, and prove it can continue.",
    steps: [
      { label: "Range", title: "First, draw the morning map", lesson: "From 9:30 to 9:45 ET, we do not trade. We mark the high and low from the first three five-minute candles. That is the opening range.", coach: "No guessing yet. We are just drawing the two boundaries that matter.", watch: ["The high of the first 15 minutes", "The low of the first 15 minutes", "A finished 5-minute candle"], avoid: "Fast opening candles can be noisy. No trade happens while the range is being built.", chartFocus: 0, question: "What is the job during the first 15 minutes?", answers: ["Buy the first strong candle", "Mark the range and wait", "Guess the day’s direction"], correct: 1, answerWhy: "Right. The range gives the trade a clear map before we risk anything." },
      { label: "Break", title: "A break gets attention — not an entry", lesson: "After 9:45, price must close outside the opening range. A quick wick through the line does not count.", coach: "The close is proof that price pushed through the boundary. But we still do not chase it.", watch: ["A completed candle outside the range", "The direction of the break", "A break before 10:30 ET"], avoid: "One fast poke outside the range can snap right back. A close matters more than excitement.", chartFocus: 1, question: "Price closes above the range. What is the disciplined move?", answers: ["Buy a call immediately", "Wait for the pullback", "Ignore every breakout"], correct: 1, answerWhy: "Right. This is a pullback strategy. We let price come back to the level instead of chasing." },
      { label: "Pullback", title: "Let price come back to the level", lesson: "For a bullish setup, price revisits the broken range high. For a bearish setup, it revisits the broken range low. This is the no-chase moment.", coach: "Patience is protection. If price never comes back, we let it go.", watch: ["The first revisit of the broken level", "Whether the level holds", "The pullback high or low"], avoid: "If price cuts through the whole range, the setup is damaged. We do not force it.", chartFocus: 2, question: "The pullback touches the level but has not bounced. What now?", answers: ["Enter now", "Wait for proof", "Add extra contracts"], correct: 1, answerWhy: "Right. A touch is not a bounce. The next candle must prove price reclaimed the level." },
      { label: "Confirm", title: "Enter only after proof", lesson: "For a bullish trade, price must reclaim the range level, beat the prior candle, and be above VWAP. For a bearish trade, the reverse must be true.", coach: "Three checks keep us out of the messy back-and-forth stuff we call chop.", watch: ["Close back beyond the range", "Break of the prior candle in the trade direction", "Correct side of VWAP"], avoid: "If price keeps crossing VWAP or the range boundary, that is chop. The correct trade is no trade.", chartFocus: 3, question: "Which sign best separates confirmation from chop?", answers: ["A cheap option premium", "Price holds beyond the level and VWAP", "A social-media alert"], correct: 1, answerWhy: "Right. The chart structure must do the convincing — not a cheap contract or a headline." },
      { label: "Protect", title: "Protect the account when the idea is wrong", lesson: "Every trade has an invalidation line: the pullback low for a bullish trade or the pullback high for a bearish trade. If price reaches it, the original idea did not work.", coach: "Exiting by a rule is a win for discipline. We protect the account so it can trade another day.", watch: ["The pullback invalidation level", "Whether price still holds its VWAP side", "The paper bot’s account-wide exits"], avoid: "Never widen a stop or add contracts to rescue a losing idea.", chartFocus: 4, question: "Price loses the pullback low on a bullish trade. What does that mean?", answers: ["Exit by the rule", "Buy more to average down", "Wait forever"], correct: 0, answerWhy: "Right. The setup is invalid. A small planned loss is far safer than turning one trade into a gamble." },
    ],
  },
  {
    id: "v2_trend",
    title: "TSLA Trend Continuation",
    shortTitle: "Trend Continuation",
    level: "Intermediate · 5 steps",
    description: "A trend needs structure, a pause, and proof that momentum has resumed before an entry is considered.",
    steps: [
      { label: "Trend", title: "Start with a real trend", lesson: "The quick trend line must be above the slower line for a call idea, or below it for a put idea. Price needs to be holding that same side.", coach: "A flat or crossed chart is not a trend. It is a wait.", watch: ["Both trend lines pointing together", "Price holding the same side", "Finished 5-minute candles"], avoid: "Crossing, flat lines are chop. We do not predict which way they will break.", chartFocus: 0, question: "What makes a trend usable?", answers: ["Lines pointing the same way", "The biggest candle", "The cheapest option"], correct: 0, answerWhy: "Right. The direction has to agree before a continuation setup can make sense." },
      { label: "Pause", title: "Let the trend breathe", lesson: "A healthy trend often pauses or pulls back. We want a controlled pause, not a collapse through the structure.", coach: "The pause gives the next move room to prove itself. We do not buy the middle of a burst.", watch: ["A shallow pullback", "Structure still holding", "Price not losing its trend side"], avoid: "A sharp reversal is not a pause. Do not call it one because you want a trade.", chartFocus: 1, question: "What do we wait for after a strong trend move?", answers: ["A controlled pause", "More random candles", "A larger position"], correct: 0, answerWhy: "Right. The pause is where the bot looks for a safer continuation opportunity." },
      { label: "Resume", title: "Wait for momentum to resume", lesson: "The completed signal candle must close through its recent mini-range in the direction of the trend.", coach: "We want the next push to show up on a finished candle—not halfway through one.", watch: ["Close beyond the mini-range", "Trend direction still intact", "Reasonable option spread"], avoid: "Do not enter while a candle is still forming. It can look strong and finish weak.", chartFocus: 2, question: "Why wait for the candle to finish?", answers: ["It gives the rule a completed fact", "It guarantees a winner", "It makes the option cheaper"], correct: 0, answerWhy: "Right. A completed candle gives the bot a real, repeatable signal instead of a moving target." },
      { label: "Confirm", title: "Enter with the trend, not against it", lesson: "When structure, direction, and the completed signal agree, the paper model records the next available option quote.", coach: "This is a simple rule: the chart gives the direction first, then the option is chosen.", watch: ["Structure and signal agree", "The next available quote", "A spread the account can handle"], avoid: "The bot never looks at a future candle to make an entry look smarter.", chartFocus: 3, question: "Which comes first: the option or the chart signal?", answers: ["The chart signal", "The option premium", "A prediction"], correct: 0, answerWhy: "Right. The chart creates the idea. The option is selected afterward to express it." },
      { label: "Protect", title: "Risk rules protect the trend trade too", lesson: "An invalidation level sits beyond the signal structure. If that structure breaks, the trend idea did not hold and the bot follows its exit rules.", coach: "A trade needs an exit before it needs hope. The same account safety rules protect every strategy.", watch: ["The structural invalidation", "VWAP and momentum changes", "The account-wide guardrails"], avoid: "Do not add contracts because a trend trade is losing.", chartFocus: 4, question: "What should happen when trend structure fails?", answers: ["Exit by the rule", "Double the position", "Move the stop farther away"], correct: 0, answerWhy: "Right. We limit the loss when the original trend story stops being true." },
    ],
  },
];

const GUARDRAILS = [
  ["Trade size", "Uses the account’s current risk setting and buying power. If one contract does not fit, the bot skips it."],
  ["Position cap", "No more than two open positions at once, and never two positions in the same ticker."],
  ["Fast protection", "A hard option stop and an early losing-trade time limit stop a bad idea from becoming an all-day hope."],
  ["Winning trade plan", "At the first target, the system can lock in part of the gain and manage the remainder with the configured trail and time rule."],
  ["Daily safety lock", "After the configured daily loss limit, new entries pause while existing positions continue to be managed."],
];

function CoachChart({ focus, trend }: { focus: number; trend: boolean }) {
  const points = trend
    ? [[56, 160, 145], [84, 146, 151], [112, 153, 133], [140, 135, 125], [168, 128, 116], [196, 116, 102], [224, 105, 113], [252, 114, 95], [280, 96, 82], [308, 84, 91], [336, 93, 69], [364, 71, 57], [392, 60, 67], [420, 68, 48], [448, 50, 39]]
    : [[56, 145, 125], [84, 126, 142], [112, 142, 131], [140, 132, 139], [168, 138, 128], [196, 128, 99], [224, 100, 87], [252, 88, 76], [280, 77, 97], [308, 98, 122], [336, 122, 111], [364, 112, 94], [392, 95, 74], [420, 75, 59], [448, 60, 66], [476, 67, 52]];
  const focusX = [103, 191, 278, 364, 462][focus];
  return <div className="rounded-xl p-3" style={{ background: "linear-gradient(145deg, var(--muted), color-mix(in srgb, var(--accent) 8%, var(--muted)))", border: "1px solid var(--border)" }}>
    <div className="flex items-center justify-between mb-2"><span className="text-xs font-semibold" style={{ color: "var(--ink)" }}>TSLA · 5-minute candle replay</span><span className="text-[11px]" style={{ color: "var(--ink-muted)" }}>Practice chart</span></div>
    <svg viewBox="0 0 540 228" className="w-full" role="img" aria-label="Illustrated TSLA candlestick lesson chart with a highlighted lesson step">
      {[34, 78, 122, 166].map((y) => <line key={y} x1="25" y1={y} x2="516" y2={y} stroke="var(--border)" />)}
      <rect x={focusX - 30} y="20" width="74" height="160" rx="8" fill="color-mix(in srgb, var(--accent) 10%, transparent)" stroke="var(--accent)" strokeDasharray="4 4" />
      {!trend && <><rect x="38" y="103" width="138" height="54" rx="6" fill="color-mix(in srgb, var(--accent) 10%, transparent)" stroke="var(--accent)" /><text x="45" y="97" fill="var(--ink-muted)" fontSize="10">Opening range</text></>}
      {points.map(([x, open, close]) => { const up = close < open; const color = up ? "var(--positive)" : "var(--negative)"; return <g key={x}><line x1={x + 6} x2={x + 6} y1={Math.min(open, close) - 10} y2={Math.max(open, close) + 10} stroke={color} /><rect x={x} y={Math.min(open, close)} width="12" height={Math.max(5, Math.abs(open - close))} rx="1.5" fill={color} /></g>; })}
      <path d="M36 159 C110 156 171 144 228 121 S322 94 382 76 S452 56 503 46" fill="none" stroke="#e39222" strokeWidth="2.5" />
      <path d="M36 174 C112 167 173 151 232 134 S324 109 384 88 S452 68 503 57" fill="none" stroke="#805ad5" strokeWidth="2.5" />
      <circle cx={focusX} cy={[132, 105, 94, 74, 62][focus]} r="7" fill="var(--accent)" stroke="var(--surface)" strokeWidth="2" />
      <text x="424" y="105" fill="#e39222" fontSize="10">VWAP</text><text x="421" y="122" fill="#805ad5" fontSize="10">Trend line</text>
      <text x="30" y="208" fill="var(--ink-muted)" fontSize="10">9:30</text><text x="150" y="208" fill="var(--ink-muted)" fontSize="10">9:45</text><text x="270" y="208" fill="var(--ink-muted)" fontSize="10">10:00</text><text x="390" y="208" fill="var(--ink-muted)" fontSize="10">10:15</text>
    </svg>
  </div>;
}

export function StrategyPlaybookExperience({ activeLessonIds }: { activeLessonIds: LessonId[] }) {
  const [selectedId, setSelectedId] = useState<LessonId>(activeLessonIds[0] ?? "v2_orb");
  const [stepIndex, setStepIndex] = useState(0);
  const [answer, setAnswer] = useState<number | null>(null);
  const [speaking, setSpeaking] = useState(false);
  const [slowMode, setSlowMode] = useState(false);
  const [showGuardrails, setShowGuardrails] = useState(false);
  const activeCourses = COURSES.filter((course) => activeLessonIds.includes(course.id));
  const course = activeCourses.find((item) => item.id === selectedId) ?? activeCourses[0];
  const step = course?.steps[stepIndex];

  useEffect(() => {
    if (activeCourses.length && !activeCourses.some((item) => item.id === selectedId)) {
      setSelectedId(activeCourses[0].id);
      setStepIndex(0);
    }
  }, [activeCourses, selectedId]);

  useEffect(() => () => window.speechSynthesis?.cancel(), []);
  if (!course || !step) return null;

  const chooseCourse = (id: LessonId) => {
    window.speechSynthesis?.cancel();
    setSpeaking(false); setSelectedId(id); setStepIndex(0); setAnswer(null);
  };
  const chooseStep = (next: number) => { setStepIndex(Math.max(0, Math.min(next, course.steps.length - 1))); setAnswer(null); };
  const speak = () => {
    if (!window.speechSynthesis) return;
    if (speaking) { window.speechSynthesis.cancel(); setSpeaking(false); return; }
    const utterance = new SpeechSynthesisUtterance(`${step.title}. ${step.lesson} Coach Celo says: ${step.coach}`);
    utterance.rate = slowMode ? 0.76 : 0.95;
    utterance.onend = () => setSpeaking(false);
    window.speechSynthesis.cancel(); window.speechSynthesis.speak(utterance); setSpeaking(true);
  };

  return <section className="flex flex-col gap-4">
    <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-3">
      <div><h2 className="text-xl font-semibold" style={{ color: "var(--ink)" }}>Strategy Playbook</h2><p className="text-sm mt-1" style={{ color: "var(--ink-muted)" }}>Learn the strategies currently turned on for paper trading, one chart decision at a time.</p></div><span className="badge badge-yellow self-start">Paper learning mode</span>
    </div>
    <div className="flex gap-2 flex-wrap" role="tablist" aria-label="Active strategy lessons">
      {activeCourses.map((item) => <button key={item.id} className={`btn ${item.id === course.id ? "btn-primary" : "btn-ghost"}`} onClick={() => chooseCourse(item.id)} role="tab" aria-selected={item.id === course.id}><span className="font-semibold">{item.shortTitle}</span><span className="opacity-75 text-xs">· {item.level}</span></button>)}
    </div>
    <div className="card overflow-hidden">
      <div className="p-4 sm:p-5 flex flex-col sm:flex-row sm:items-center justify-between gap-3" style={{ background: "linear-gradient(125deg, color-mix(in srgb, var(--accent) 15%, var(--surface)), var(--surface) 62%)", borderBottom: "1px solid var(--border)" }}>
        <div className="flex gap-3 items-center"><div className="w-12 h-12 rounded-2xl overflow-hidden shrink-0" style={{ background: "color-mix(in srgb, var(--accent) 12%, var(--surface))", border: "2px solid color-mix(in srgb, var(--accent) 45%, var(--border))" }}><img src={COACH_IMAGE} alt="Coach Celo" className="w-full h-full object-contain object-bottom" /></div><div><p className="text-[11px] uppercase tracking-[.16em] font-semibold" style={{ color: "var(--accent)" }}>Coach Celo · Learn by replay</p><h3 className="text-lg font-semibold mt-0.5" style={{ color: "var(--ink)" }}>{course.title}</h3><p className="text-xs mt-1" style={{ color: "var(--ink-muted)" }}>{course.description}</p></div></div>
        <button className="btn btn-ghost btn-sm self-start sm:self-auto" onClick={() => { chooseStep(0); setShowGuardrails(false); }}><RotateCcw size={14} /> Restart lesson</button>
      </div>
      <div className="p-4 sm:p-5 grid gap-4" style={{ gridTemplateColumns: "minmax(0, 1.55fr) minmax(270px, .85fr)" }}>
        <div className="min-w-0 flex flex-col gap-3"><CoachChart focus={step.chartFocus} trend={course.id === "v2_trend"} /><div className="flex gap-1.5 flex-wrap" aria-label="Lesson steps">{course.steps.map((item, index) => <button key={item.label} className="rounded-full px-2.5 py-1.5 text-[11px] font-semibold" onClick={() => chooseStep(index)} style={{ border: index === stepIndex ? "1px solid var(--accent)" : "1px solid var(--border)", background: index === stepIndex ? "var(--accent)" : "var(--surface)", color: index === stepIndex ? "white" : "var(--ink-muted)" }}>{index + 1}. {item.label}</button>)}</div><div className="flex items-center justify-between gap-2"><button className="btn btn-ghost btn-sm" disabled={stepIndex === 0} onClick={() => chooseStep(stepIndex - 1)}><ChevronLeft size={15} /> Back</button><span className="text-xs font-semibold" style={{ color: "var(--ink-muted)" }}>Step {stepIndex + 1} of {course.steps.length}</span><button className="btn btn-primary btn-sm" onClick={() => chooseStep(stepIndex === course.steps.length - 1 ? 0 : stepIndex + 1)}>{stepIndex === course.steps.length - 1 ? "Replay" : "Next"} <ChevronRight size={15} /></button></div></div>
        <aside className="rounded-xl p-4 flex flex-col gap-4" style={{ background: "#122854", color: "white" }}>
          <div className="flex items-start gap-3"><img src={COACH_IMAGE} alt="Coach Celo, your strategy instructor" className="w-16 h-24 object-contain object-bottom shrink-0" /><div><p className="text-[11px] uppercase tracking-[.15em] font-semibold" style={{ color: "#a9c7ff" }}>Coach Celo</p><h3 className="text-base font-semibold mt-1">{step.title}</h3><p className="text-xs leading-relaxed mt-1" style={{ color: "#d4e2ff" }}>{step.coach}</p></div></div>
          <div className="rounded-lg p-3 text-sm leading-relaxed" style={{ background: "white", color: "#263653", borderLeft: "3px solid #4a83ff" }}>{slowMode ? <><strong>Let’s slow down:</strong> {step.lesson}</> : <><strong>Coach Celo says:</strong> {step.lesson}</>}</div>
          <div className="flex gap-2 flex-wrap"><button className="btn btn-sm" onClick={speak} style={{ background: "#2862e9", color: "white", borderColor: "#2862e9" }}>{speaking ? <Pause size={14} /> : <Volume2 size={14} />}{speaking ? "Pause Coach Celo" : "Hear Coach Celo"}</button><button className="btn btn-sm" onClick={() => setSlowMode((value) => !value)} style={{ background: "transparent", color: "#d4e2ff", borderColor: "#4c6798" }}>{slowMode ? "Normal speed" : "Slow it down"}</button></div>
          <div><p className="text-[11px] uppercase tracking-[.15em] font-semibold mb-2" style={{ color: "#a9c7ff" }}>What to watch</p><ul className="flex flex-col gap-2">{step.watch.map((item) => <li key={item} className="flex gap-2 text-xs leading-relaxed" style={{ color: "#eff5ff" }}><Check size={14} className="shrink-0 mt-0.5" style={{ color: "#69df9c" }} />{item}</li>)}</ul></div>
          <div className="rounded-lg p-3 text-xs leading-relaxed" style={{ background: "#3f2436", color: "#f7d9e7", borderLeft: "3px solid #ff688d" }}><strong style={{ color: "white" }}>Avoid the chop:</strong> {step.avoid}</div>
          <button className="btn btn-sm self-start mt-auto" onClick={() => setShowGuardrails((value) => !value)} style={{ background: showGuardrails ? "#4a83ff" : "transparent", color: "white", borderColor: "#4c6798" }}><ShieldCheck size={14} />{showGuardrails ? "Back to lesson" : "How the bot protects the account"}</button>
        </aside>
      </div>
      {showGuardrails ? <div className="mx-4 sm:mx-5 mb-5 rounded-xl p-4" style={{ background: "color-mix(in srgb, var(--accent) 7%, var(--surface))", border: "1px solid var(--border)" }}><div className="flex gap-3 items-start"><img src={COACH_IMAGE} alt="Coach Celo" className="w-12 h-16 object-contain object-bottom shrink-0" /><div><p className="text-sm font-semibold" style={{ color: "var(--ink)" }}>Coach Celo explains the account guardrails</p><p className="text-xs mt-1 leading-relaxed" style={{ color: "var(--ink-muted)" }}>These rules are shared by every paper strategy. They are meant to control risk; they do not guarantee profit.</p></div></div><div className="grid gap-2 mt-4" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(210px, 1fr))" }}>{GUARDRAILS.map(([title, detail]) => <div key={title} className="rounded-lg p-3" style={{ background: "var(--surface)", border: "1px solid var(--border)" }}><p className="text-xs font-semibold" style={{ color: "var(--ink)" }}>{title}</p><p className="text-xs leading-relaxed mt-1" style={{ color: "var(--ink-muted)" }}>{detail}</p></div>)}</div><button className="btn btn-primary btn-sm mt-4" onClick={() => { setSlowMode(false); const next = course.steps.length - 1; chooseStep(next); }}><Play size={14} />Hear the exit lesson next</button></div> : <div className="mx-4 sm:mx-5 mb-5 rounded-xl p-4" style={{ background: "var(--surface)", border: "1px solid var(--border)" }}><p className="text-sm font-semibold" style={{ color: "var(--ink)" }}>Try it yourself</p><p className="text-xs mt-1" style={{ color: "var(--ink-muted)" }}>{step.question}</p><div className="grid gap-2 mt-3" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(170px, 1fr))" }}>{step.answers.map((choice, index) => <button key={choice} className="btn text-left justify-start" onClick={() => setAnswer(index)} style={answer === index ? { borderColor: index === step.correct ? "var(--positive)" : "var(--negative)", background: index === step.correct ? "var(--positive-bg)" : "var(--negative-bg)" } : undefined}>{choice}</button>)}</div>{answer !== null && <p className="text-xs mt-3 leading-relaxed" style={{ color: answer === step.correct ? "var(--positive)" : "var(--ink-muted)" }}>{answer === step.correct ? step.answerWhy : `Not quite. ${step.answerWhy}`}</p>}</div>}
    </div>
  </section>;
}
