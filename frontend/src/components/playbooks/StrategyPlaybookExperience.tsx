import { useEffect, useRef, useState } from "react";
import {
  Check, ChevronLeft, ChevronRight, Play, ShieldCheck,
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

const COACH_IMAGE = "/images/coach-celo-v5.png?v=1";

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

function CoachChart({ focus }: { focus: number }) {
  // A deliberately short replay: beginners can see the entire ORB story in one screen.
  // Each tuple is x, open, close, high, low (smaller y = higher price).
  const candles = [[74,288,272,299,263],[112,272,280,289,259],[150,280,266,285,254],[188,266,251,273,243],[226,251,260,269,238],[264,260,246,268,237],[302,246,221,253,211],[340,221,205,230,195],[378,205,214,222,198],[416,214,239,245,206],[454,239,230,248,222],[492,230,203,237,194],[530,203,188,211,178],[568,188,173,196,165],[606,173,181,190,166],[644,181,160,187,151],[682,160,146,168,138]];
  const focusX = [150, 302, 416, 492, 644][focus];
  const focusY = [273, 221, 239, 203, 160][focus];
  return <div className="rounded-xl p-3 sm:p-4" style={{ background: "#fff", border: "1px solid #e8edf5" }}>
    <div className="flex items-center justify-between gap-2 mb-3"><span className="text-xs font-semibold" style={{ color: "var(--ink)" }}>TSLA · 5-minute candle replay</span><span className="text-[11px] shrink-0" style={{ color: "var(--ink-muted)" }}>A single clean setup</span></div>
    <svg viewBox="0 0 760 385" className="w-full" role="img" aria-label="TSLA lesson chart showing a three candle opening range, breakout, pullback, confirmation, VWAP and fast trend line">
      {[62,118,174,230,286].map((y) => <line key={`h-${y}`} x1="40" y1={y} x2="710" y2={y} stroke="#edf1f7" strokeWidth="1" />)}
      {[40,116,192,268,344,420,496,572,648,710].map((x) => <line key={`v-${x}`} x1={x} y1="62" x2={x} y2="286" stroke="#f4f6f9" strokeWidth="1" />)}
      <rect x="54" y="250" width="112" height="49" rx="5" fill="#eaf2ff" stroke="#2870f4" strokeWidth="1.5" strokeDasharray="5 4" />
      <text x="63" y="244" fill="#1768e8" fontSize="12" fontWeight="700">OPENING RANGE · 9:30–9:45</text>
      <line x1="54" y1="250" x2="166" y2="250" stroke="#2870f4" strokeWidth="1.6"/><text x="172" y="254" fill="#1768e8" fontSize="10">range high</text>
      <line x1="54" y1="299" x2="166" y2="299" stroke="#2870f4" strokeWidth="1.6"/><text x="172" y="303" fill="#1768e8" fontSize="10">range low</text>
      <rect x={focusX - 23} y={Math.max(58, focusY - 44)} width="50" height="92" rx="6" fill="#2d73f5" fillOpacity=".05" stroke="#2d73f5" strokeWidth="1.3" strokeDasharray="4 4" />
      {candles.map(([x, open, close, high, low]) => { const green = close < open; const color = green ? "#19a85b" : "#ea514c"; return <g key={x}><line x1={x + 8} x2={x + 8} y1={high} y2={low} stroke={color} strokeWidth="1.6"/><rect x={x} y={Math.min(open, close)} width="16" height={Math.max(6, Math.abs(open - close))} rx="1.5" fill={color}/></g>; })}
      <path d="M54 304 C154 300 225 282 302 259 S465 215 690 183" fill="none" stroke="#f7921e" strokeWidth="2" />
      <path d="M54 314 C160 302 236 277 318 247 S500 191 690 153" fill="none" stroke="#7d49dd" strokeWidth="2" />
      <line x1="310" y1="181" x2="310" y2="222" stroke="#25354d" strokeWidth="1.2" /><circle cx="310" cy="222" r="4" fill="#25354d"/><rect x="286" y="156" width="49" height="19" rx="4" fill="#182132"/><text x="293" y="169" fill="white" fontSize="10" fontWeight="700">BREAK</text>
      <rect x="400" y="202" width="58" height="44" rx="4" fill="#eff7ff" stroke="#2870f4" strokeWidth="1.5" strokeDasharray="5 4"/><text x="404" y="196" fill="#2870f4" fontSize="11" fontWeight="700">PULLBACK</text>
      <line x1="505" y1="118" x2="505" y2="188" stroke="#25354d" strokeWidth="1.2"/><circle cx="505" cy="188" r="4" fill="#25354d"/><rect x="478" y="95" width="55" height="19" rx="4" fill="#182132"/><text x="485" y="108" fill="white" fontSize="10" fontWeight="700">PROOF</text>
      <text x="652" y="184" fill="#ed8515" fontSize="12" fontWeight="700">VWAP</text><text x="630" y="150" fill="#7650d6" fontSize="12" fontWeight="700">fast EMA</text>
      <circle cx={focusX} cy={focusY} r="7" fill="#2870f4" stroke="white" strokeWidth="3"/>
      {[[54,"9:30"],[166,"9:45"],[310,"10:00"],[455,"10:15"],[600,"10:30"],[682,"10:45"]].map(([x,label]) => <text key={String(x)} x={Number(x)} y="329" fill="#6b778c" fontSize="11">{label}</text>)}
      <text x="42" y="360" fill="#68768a" fontSize="11">1. Build range</text><text x="220" y="360" fill="#68768a" fontSize="11">2. Break</text><text x="382" y="360" fill="#68768a" fontSize="11">3. Pull back</text><text x="530" y="360" fill="#68768a" fontSize="11">4. Confirm</text>
    </svg>
  </div>;
}

export function StrategyPlaybookExperience({ activeLessonIds }: { activeLessonIds: LessonId[] }) {
  const [selectedId, setSelectedId] = useState<LessonId>(activeLessonIds[0] ?? "v2_orb");
  const [stepIndex, setStepIndex] = useState(0);
  const [answer, setAnswer] = useState<number | null>(null);
  const [showGuardrails, setShowGuardrails] = useState(false);
  const [narrationPlaying, setNarrationPlaying] = useState(false);
  const [narrationProgress, setNarrationProgress] = useState(0);
  const [narrationError, setNarrationError] = useState(false);
  const audioRef = useRef<HTMLAudioElement>(null);
  const activeCourses = COURSES.filter((course) => activeLessonIds.includes(course.id));
  const course = activeCourses.find((item) => item.id === selectedId) ?? activeCourses[0];
  const step = course?.steps[stepIndex];

  useEffect(() => {
    if (activeCourses.length && !activeCourses.some((item) => item.id === selectedId)) {
      setSelectedId(activeCourses[0].id);
      setStepIndex(0);
    }
  }, [activeCourses, selectedId]);

  if (!course || !step) return null;
  const audioSrc = `/audio/coach-celo/${course.id}/${step.label.toLowerCase()}.mp3`;

  const chooseCourse = (id: LessonId) => {
    audioRef.current?.pause(); setNarrationPlaying(false); setNarrationProgress(0); setNarrationError(false);
    setSelectedId(id); setStepIndex(0); setAnswer(null);
  };
  const chooseStep = (next: number) => { audioRef.current?.pause(); setNarrationPlaying(false); setNarrationProgress(0); setNarrationError(false); setStepIndex(Math.max(0, Math.min(next, course.steps.length - 1))); setAnswer(null); };
  const toggleNarration = () => {
    const audio = audioRef.current;
    if (!audio) return;
    if (audio.paused) audio.play().catch(() => setNarrationError(true));
    else audio.pause();
  };

  return <section className="flex flex-col gap-4 max-w-[1500px]">
    <div><h2 className="text-[28px] leading-tight font-bold tracking-tight" style={{ color: "#102950" }}>Strategy Playbook</h2><p className="text-sm mt-1" style={{ color: "var(--ink-muted)" }}>Learn our current paper strategies one visual lesson at a time.</p></div>
    <div className="flex gap-3 flex-wrap" role="tablist" aria-label="Active strategy lessons">
      {activeCourses.map((item) => <button key={item.id} onClick={() => chooseCourse(item.id)} role="tab" aria-selected={item.id === course.id} className="rounded-lg px-5 py-3 text-sm font-semibold transition-colors" style={{ border: item.id === course.id ? "1.5px solid #2970f6" : "1px solid var(--border)", color: item.id === course.id ? "#1e66ed" : "var(--ink-muted)", background: item.id === course.id ? "#f6f9ff" : "var(--surface)", boxShadow: item.id === course.id ? "0 4px 14px rgba(41,112,246,.08)" : "none" }}>{item.shortTitle}</button>)}
    </div>
    <div className="grid gap-4 items-stretch" style={{ gridTemplateColumns: "minmax(0, 1fr) minmax(300px, .34fr)" }}>
      <div className="card overflow-hidden p-0" style={{ boxShadow: "0 10px 32px rgba(23,47,82,.07)" }}>
        <div className="px-5 pt-4 pb-3 grid gap-4 items-center" style={{ gridTemplateColumns: "minmax(250px, .55fr) minmax(400px, 1fr)", borderBottom: "1px solid var(--border)" }}>
          <div className="flex items-center gap-3"><div className="w-10 h-10 rounded-full grid place-items-center font-bold text-base text-white" style={{ background: course.id === "v2_orb" ? "#e8262d" : "#296df5" }}>{course.id === "v2_orb" ? "T" : "↗"}</div><div><div className="flex items-center gap-2"><span className="font-bold text-sm" style={{ color: "var(--ink)" }}>TSLA</span><span className="text-sm" style={{ color: "var(--ink-muted)" }}>{course.shortTitle}</span><span className="rounded-md px-2 py-0.5 text-[11px] font-bold" style={{ background: "#edf4ff", color: "#2368e9" }}>5m</span></div><p className="text-[11px] mt-1" style={{ color: "var(--ink-muted)" }}>Lesson: {stepIndex + 1} of {course.steps.length}</p></div></div>
          <div className="flex items-start justify-between gap-1" aria-label="Lesson steps">{course.steps.map((item, index) => <button key={item.label} onClick={() => chooseStep(index)} className="flex-1 min-w-0 flex flex-col items-center gap-1.5 group"><span className="w-7 h-7 rounded-full grid place-items-center text-xs font-bold transition-colors" style={{ background: index === stepIndex ? "#1f6fff" : "#f1f3f7", color: index === stepIndex ? "white" : "#546176", boxShadow: index === stepIndex ? "0 0 0 4px #eaf1ff" : "none" }}>{index + 1}</span><span className="text-[11px] font-medium whitespace-nowrap" style={{ color: index === stepIndex ? "#1f6fff" : "#536075" }}>{item.label}</span></button>)}</div>
        </div>
        <div className="p-5 flex flex-col gap-4">
          <div className="min-w-0"><CoachChart focus={step.chartFocus} /></div>
          <div className="flex items-center justify-between gap-3"><button className="btn btn-ghost btn-sm" disabled={stepIndex === 0} onClick={() => chooseStep(stepIndex - 1)}><ChevronLeft size={15} /> Back</button><div className="flex-1 max-w-[440px] h-1 rounded-full" style={{ background: "#e5ecf8" }}><div className="h-full rounded-full" style={{ width: `${((stepIndex + 1) / course.steps.length) * 100}%`, background: "#2870f4" }} /></div><button className="btn btn-primary btn-sm" onClick={() => chooseStep(stepIndex === course.steps.length - 1 ? 0 : stepIndex + 1)}>{stepIndex === course.steps.length - 1 ? "Replay" : "Next"} <ChevronRight size={15} /></button></div>
        </div>
        {showGuardrails ? <div className="mx-5 mb-5 rounded-xl p-4" style={{ background: "color-mix(in srgb, var(--accent) 7%, var(--surface))", border: "1px solid var(--border)" }}><div className="flex gap-3 items-start"><img src={COACH_IMAGE} alt="Coach Celo" className="w-12 h-16 object-contain object-bottom shrink-0" /><div><p className="text-sm font-semibold" style={{ color: "var(--ink)" }}>Coach Celo explains the account guardrails</p><p className="text-xs mt-1 leading-relaxed" style={{ color: "var(--ink-muted)" }}>These rules are shared by every paper strategy. They control risk across the account.</p></div></div><div className="grid gap-2 mt-4" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(210px, 1fr))" }}>{GUARDRAILS.map(([title, detail]) => <div key={title} className="rounded-lg p-3" style={{ background: "var(--surface)", border: "1px solid var(--border)" }}><p className="text-xs font-semibold" style={{ color: "var(--ink)" }}>{title}</p><p className="text-xs leading-relaxed mt-1" style={{ color: "var(--ink-muted)" }}>{detail}</p></div>)}</div></div> : <div className="mx-5 mb-5 rounded-xl p-4" style={{ background: "#fbfcff", border: "1px solid #e7edf7" }}><p className="text-base font-bold" style={{ color: "var(--ink)" }}>Try it yourself</p><p className="text-xs mt-1" style={{ color: "var(--ink-muted)" }}>{step.question}</p><div className="grid gap-2 mt-3" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(170px, 1fr))" }}>{step.answers.map((choice, index) => <button key={choice} className="btn text-left justify-start" onClick={() => setAnswer(index)} style={answer === index ? { borderColor: index === step.correct ? "var(--positive)" : "var(--negative)", background: index === step.correct ? "var(--positive-bg)" : "var(--negative-bg)" } : undefined}><span className="w-6 h-6 rounded-full grid place-items-center text-xs mr-1" style={{ background: "#edf4ff", color: "#1f6fff" }}>{index + 1}</span>{choice}</button>)}</div>{answer !== null && <p className="text-xs mt-3 leading-relaxed" style={{ color: answer === step.correct ? "var(--positive)" : "var(--ink-muted)" }}>{answer === step.correct ? step.answerWhy : `Not quite. ${step.answerWhy}`}</p>}</div>}
      </div>
        <aside className="rounded-2xl overflow-hidden flex flex-col" style={{ background: "linear-gradient(160deg, #08234a 0%, #0a2e63 100%)", color: "white", boxShadow: "0 18px 36px rgba(11, 35, 75, .15)" }}>
          <audio ref={audioRef} src={audioSrc} preload="metadata" onPlay={() => setNarrationPlaying(true)} onPause={() => setNarrationPlaying(false)} onEnded={() => { setNarrationPlaying(false); setNarrationProgress(0); }} onError={() => setNarrationError(true)} onTimeUpdate={(event) => { const audio = event.currentTarget; setNarrationProgress(audio.duration ? (audio.currentTime / audio.duration) * 100 : 0); }} />
          <div className="px-5 pt-5 h-[270px] relative overflow-hidden">
            <p className="relative z-10 text-center text-base font-bold">Coach Celo</p><div className="mx-auto mt-1 w-8 h-0.5 rounded-full" style={{ background: "#337dff" }} />
            <div className="absolute inset-x-0 top-[42px] h-[340px] grid place-items-start" style={{ background: "radial-gradient(circle at 50% 40%, rgba(55,124,255,.22), transparent 54%)" }}><img src={COACH_IMAGE} alt="Coach Celo, your strategy instructor" className="h-[370px] w-auto max-w-[88%] object-contain object-top" /></div>
          </div>
          <div className="px-4 pb-4 flex flex-col gap-4">
            <div className="relative -mt-2 rounded-2xl p-4 text-sm leading-relaxed" style={{ background: "#fff", color: "#273955", boxShadow: "0 8px 18px rgba(0,0,0,.17)" }}><span className="absolute -top-2 left-1/2 -translate-x-1/2 w-4 h-4 rotate-45 bg-white" /><div className="relative"><strong>Coach Celo says:</strong> {step.lesson}<p className="mt-2 text-xs leading-relaxed" style={{ color: "#64718a" }}>{step.coach}</p></div></div>
            <button className="w-full rounded-xl px-3 py-2.5 flex items-center gap-3 text-left" onClick={toggleNarration} style={{ background: "rgba(100,151,255,.15)", border: "1px solid rgba(173,204,255,.34)", color: "white" }} aria-label={narrationPlaying ? "Pause Coach Celo narration" : "Play Coach Celo narration"}>
              <span className="w-8 h-8 shrink-0 rounded-full grid place-items-center" style={{ background: "#3c7af9" }}>{narrationPlaying ? <span className="text-xs font-black">Ⅱ</span> : <Play size={14} fill="white" />}</span>
              <div className="min-w-0 flex-1"><p className="text-xs font-semibold">{narrationError ? "Narration unavailable" : "Hear Coach Celo"}</p><div className="mt-1.5 h-1.5 rounded-full overflow-hidden" style={{ background: "rgba(255,255,255,.22)" }}><div className="h-full rounded-full" style={{ width: `${narrationProgress || 0}%`, minWidth: narrationProgress ? undefined : "8px", background: "#80b1ff" }} /></div></div><span className="text-[10px]" style={{ color: "#bcd2ff" }}>{narrationPlaying ? "Playing" : "Audio"}</span>
            </button>
            <div><p className="text-[11px] uppercase tracking-[.15em] font-semibold mb-2" style={{ color: "#a9c7ff" }}>What to watch</p><ul className="flex flex-col gap-2.5">{step.watch.map((item) => <li key={item} className="flex gap-2 text-xs leading-relaxed" style={{ color: "#eff5ff" }}><Check size={14} className="shrink-0 mt-0.5" style={{ color: "#69df9c" }} />{item}</li>)}</ul></div>
            <div className="rounded-xl p-3 text-xs leading-relaxed" style={{ background: "rgba(255,105,143,.16)", color: "#ffdce8", borderLeft: "3px solid #ff7295" }}><strong style={{ color: "white" }}>Avoid the chop:</strong> {step.avoid}</div>
            <button className="btn btn-sm self-start" onClick={() => setShowGuardrails((value) => !value)} style={{ background: showGuardrails ? "#4a83ff" : "transparent", color: "white", borderColor: "#5576aa" }}><ShieldCheck size={14} />{showGuardrails ? "Back to lesson" : "See the safety rules"}</button>
          </div>
        </aside>
    </div>
  </section>;
}
