import { useCallback, useEffect, useMemo, useState } from "react";
import { Bot, Check, ChevronLeft, ChevronRight, Pause, Play, RotateCcw, Volume2 } from "lucide-react";

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
    watch: ["The pullback low or high that invalidates the setup", "Whether price still holds the intended side of the range", "The current paper-pilot risk and time exit rules"],
    avoid: "Do not widen a stop or add contracts because a trade is losing. A losing trade is information, not a reason to gamble.",
    chartStage: "exit",
    decision: { prompt: "Price loses the pullback low on a bullish trade. What does that tell us?", choices: ["The setup is invalid — exit by the rule", "Buy more to lower the average", "Wait forever for a rebound"], correct: 0, explanation: "Correct. The exit is not a punishment; it is proof that we protect a small account when the original idea is wrong." },
  },
];

function CoachChart({ stage }: { stage: CoachBeat["chartStage"] }) {
  const index = ["range", "breakout", "retest", "confirm", "exit"].indexOf(stage);
  const labels = ["Opening range", "Break", "Pullback", "Confirmation", "Exit plan"];
  return (
    <div className="rounded-xl p-3" style={{ background: "linear-gradient(150deg, var(--muted), color-mix(in srgb, var(--accent) 8%, var(--muted)))", border: "1px solid var(--border)" }}>
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs font-semibold" style={{ color: "var(--ink)" }}>TSLA · 5-minute lesson chart</span>
        <span className="text-[11px]" style={{ color: "var(--ink-muted)" }}>Not a live chart</span>
      </div>
      <svg viewBox="0 0 660 260" className="w-full" role="img" aria-label="Illustrated opening-range pullback chart with the current lesson moment highlighted">
        {[40, 90, 140, 190].map((y) => <line key={y} x1="35" y1={y} x2="645" y2={y} stroke="var(--border)" strokeWidth="1" />)}
        <rect x="42" y="104" width="144" height="55" rx="6" fill="color-mix(in srgb, var(--accent) 11%, transparent)" stroke="var(--accent)" strokeWidth={index === 0 ? 2 : 1} />
        <text x="49" y="98" fill="var(--ink-muted)" fontSize="11">Opening range</text>
        <path d="M42 148 C90 137 138 145 184 131 S246 89 300 62 S350 71 397 132 S455 149 502 111 S568 65 640 78" fill="none" stroke="var(--accent)" strokeWidth="3" />
        <path d="M42 157 C140 153 197 145 260 132 S380 129 472 120 S580 104 640 94" fill="none" stroke="#df911f" strokeWidth="2" />
        <path d="M42 166 C135 160 211 144 287 128 S372 121 454 118 S574 102 640 91" fill="none" stroke="#8359d5" strokeWidth="2" />
        <line x1="197" y1="132" x2="197" y2="70" stroke="var(--accent)" strokeDasharray="4 4" />
        <circle cx="197" cy="132" r={index === 1 ? 9 : 5} fill="var(--accent)" />
        <circle cx="389" cy="137" r={index === 2 ? 9 : 5} fill="var(--accent)" />
        <circle cx="481" cy="111" r={index === 3 ? 9 : 5} fill="var(--accent)" />
        <circle cx="556" cy="83" r={index === 4 ? 9 : 5} fill={stage === "exit" ? "var(--negative)" : "var(--accent)"} />
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
  const [isPlaying, setIsPlaying] = useState(false);
  const [answer, setAnswer] = useState<number | null>(null);
  const beat = ORB_BEATS[beatIndex];

  const stop = useCallback(() => {
    window.speechSynthesis?.cancel();
    setIsPlaying(false);
  }, []);

  const play = useCallback(() => {
    if (!("speechSynthesis" in window)) return;
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(beat.voice);
    utterance.rate = 0.96;
    utterance.pitch = 1;
    utterance.onend = () => setIsPlaying(false);
    utterance.onerror = () => setIsPlaying(false);
    window.speechSynthesis.speak(utterance);
    setIsPlaying(true);
  }, [beat.voice]);

  useEffect(() => () => window.speechSynthesis?.cancel(), []);
  useEffect(() => { setAnswer(null); stop(); }, [beatIndex, stop]);

  const answerCopy = useMemo(() => {
    if (!beat.decision || answer === null) return "Choose an answer to practice the habit before you see the next part.";
    return answer === beat.decision.correct ? beat.decision.explanation : `Not this time. ${beat.decision.explanation}`;
  }, [answer, beat.decision]);

  return (
    <section className="card overflow-hidden">
      <div className="p-4 sm:p-5" style={{ background: "linear-gradient(125deg, color-mix(in srgb, var(--accent) 15%, var(--surface)), var(--surface) 62%)", borderBottom: "1px solid var(--border)" }}>
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div className="flex gap-3 items-center">
            <div className="w-11 h-11 rounded-2xl flex items-center justify-center shrink-0" style={{ background: "radial-gradient(circle at 35% 30%, #e9f5ff 0 10%, #8eb7ff 31%, #5e77e8 59%, #714fc0 100%)", boxShadow: "0 0 26px color-mix(in srgb, var(--accent) 35%, transparent)" }}><Bot size={22} color="white" /></div>
            <div><p className="text-[11px] uppercase tracking-[0.16em] font-semibold" style={{ color: "var(--accent)" }}>Coach Celo · Learn by replay</p><h2 className="text-lg font-semibold mt-0.5" style={{ color: "var(--ink)" }}>TSLA Opening-Range Pullback</h2><p className="text-xs mt-1" style={{ color: "var(--ink-muted)" }}>Paper-only lesson based on the bot’s current V2 TSLA setup — not investment advice.</p></div>
          </div>
          <button className="btn btn-primary btn-sm self-start sm:self-auto" onClick={isPlaying ? stop : play} aria-label={isPlaying ? "Pause voice lesson" : "Play voice lesson"}>{isPlaying ? <Pause size={14} /> : <Play size={14} />}{isPlaying ? "Pause coach" : "Play coach"}</button>
        </div>
      </div>
      <div className="p-4 sm:p-5 grid gap-4" style={{ gridTemplateColumns: "minmax(0, 1.6fr) minmax(250px, .85fr)" }}>
        <div className="min-w-0 flex flex-col gap-3">
          <CoachChart stage={beat.chartStage} />
          <div className="flex items-center justify-between gap-2">
            <button className="btn btn-ghost btn-sm" disabled={beatIndex === 0} onClick={() => setBeatIndex((index) => Math.max(0, index - 1))}><ChevronLeft size={15} /> Back</button>
            <div className="flex gap-1.5" aria-label={`Lesson step ${beatIndex + 1} of ${ORB_BEATS.length}`}>{ORB_BEATS.map((item, index) => <button key={item.shortTitle} aria-label={`Go to ${item.shortTitle}`} onClick={() => setBeatIndex(index)} className="w-2.5 h-2.5 rounded-full border-0" style={{ background: index === beatIndex ? "var(--accent)" : index < beatIndex ? "color-mix(in srgb, var(--accent) 48%, var(--border))" : "var(--border)", cursor: "pointer" }} />)}</div>
            <button className="btn btn-primary btn-sm" disabled={beatIndex === ORB_BEATS.length - 1} onClick={() => setBeatIndex((index) => Math.min(ORB_BEATS.length - 1, index + 1))}>Next <ChevronRight size={15} /></button>
          </div>
        </div>
        <aside className="rounded-xl p-4 flex flex-col gap-4" style={{ background: "var(--muted)", border: "1px solid var(--border)" }}>
          <div><div className="flex items-center gap-2 text-xs font-semibold" style={{ color: "var(--accent)" }}><Volume2 size={14} /> Lesson {beatIndex + 1} of {ORB_BEATS.length}</div><h3 className="text-base font-semibold mt-2" style={{ color: "var(--ink)" }}>{beat.title}</h3><p className="text-sm leading-relaxed mt-2" style={{ color: "var(--ink-muted)" }}>{beat.coach}</p></div>
          <div><p className="text-[11px] uppercase tracking-widest font-semibold mb-2" style={{ color: "var(--ink-muted)" }}>What to watch</p><ul className="flex flex-col gap-2">{beat.watch.map((item) => <li key={item} className="flex gap-2 text-xs" style={{ color: "var(--ink)" }}><Check size={14} className="shrink-0 mt-0.5" style={{ color: "var(--positive)" }} />{item}</li>)}</ul></div>
          <div className="rounded-lg p-3 text-xs leading-relaxed" style={{ background: "var(--negative-bg)", color: "var(--ink-muted)", borderLeft: "3px solid var(--negative)" }}><strong style={{ color: "var(--ink)" }}>Avoid the chop:</strong> {beat.avoid}</div>
          <button className="btn btn-ghost btn-sm mt-auto self-start" onClick={() => { setBeatIndex(0); setAnswer(null); stop(); }}><RotateCcw size={13} /> Restart lesson</button>
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
