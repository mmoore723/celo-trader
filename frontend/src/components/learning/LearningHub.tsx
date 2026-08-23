import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { BookOpen, BrainCircuit, GraduationCap, RotateCcw, Trophy } from "lucide-react";

import { api, type LearningExample, type LearningExampleCategory, type ReviewedStrategyCatalogEntry } from "../../lib/api";
import { scoreLearningAnswer, type LearningPracticeAnswer } from "../../lib/learningSemantics.js";
import { TradeChart } from "../charts/TradeChart";
import { StrategyPlaybookExperience, type LessonId } from "../playbooks/StrategyPlaybookExperience";
import { useAuth } from "../../contexts/AuthContext";

type HubTab = "learn" | "practice" | "replay" | "progress";
type PracticeAnswer = LearningPracticeAnswer;

const CATEGORY_LABELS: Record<LearningExampleCategory, string> = {
  clean_win: "60m follow-through",
  valid_loss: "60m non-follow-through",
  false_breakout_or_chop: "False breakout / chop",
  rejected_missing_condition: "Missing condition",
  ambiguous_no_trade: "Ambiguous · no trade",
};

const TABS: Array<{ id: HubTab; label: string; icon: typeof BookOpen }> = [
  { id: "learn", label: "Learn", icon: BookOpen },
  { id: "practice", label: "Practice", icon: GraduationCap },
  { id: "replay", label: "Replay", icon: RotateCcw },
  { id: "progress", label: "Progress", icon: Trophy },
];

function progressKey(owner: string, exampleId: string) {
  return `celo-learning-example:${owner}:${exampleId}`;
}

function ExampleWorkspace({ example, mode, progressOwner }: { example: LearningExample; mode: "practice" | "replay"; progressOwner: string }) {
  const decisionCount = Math.min(example.bars.length, example.decision_bar_index + 1);
  const [answer, setAnswer] = useState<PracticeAnswer | null>(null);
  const [revealCount, setRevealCount] = useState(decisionCount);
  const [coachMode, setCoachMode] = useState<"prompt" | "facts" | "outcome">("prompt");
  const answered = answer !== null;
  const correct = answer ? scoreLearningAnswer(example.category, example.direction, answer) : false;

  useEffect(() => {
    setAnswer(null);
    setRevealCount(decisionCount);
    setCoachMode("prompt");
  }, [example.example_id, decisionCount]);

  useEffect(() => {
    if (answered) localStorage.setItem(progressKey(progressOwner, example.example_id), correct ? "correct" : "review");
  }, [answered, correct, example.example_id, progressOwner]);

  const visibleCount = mode === "practice" && !answered ? decisionCount : revealCount;

  return <div className="grid gap-4" style={{ gridTemplateColumns: "minmax(0, 1.7fr) minmax(270px, .8fr)" }}>
    <section className="card overflow-hidden">
      <div className="px-4 py-3 flex items-center justify-between gap-3 flex-wrap" style={{ borderBottom: "1px solid var(--border)" }}>
        <div>
          <p className="text-sm font-semibold" style={{ color: "var(--ink)" }}>{example.ticker} · {example.strategy_id}</p>
          <p className="text-xs" style={{ color: "var(--ink-muted)" }}>{new Date(example.observed_at).toLocaleString()} · v{example.strategy_version}</p>
        </div>
        <span className="badge badge-blue">{mode === "practice" && !answered ? "Frozen decision" : CATEGORY_LABELS[example.category]}</span>
      </div>
      <TradeChart
        bars={example.bars}
        ticker={example.ticker}
        revealCount={visibleCount}
        viewportKey={`learning:${example.example_id}:${mode}`}
        showStructure={false}
        showSwings={false}
        showRsi={false}
        showMacd={false}
        height={440}
      />
      {mode === "replay" && <div className="p-4 flex items-center gap-3">
        <button className="btn btn-sm btn-ghost" onClick={() => setRevealCount(decisionCount)}>Reset</button>
        <input
          className="grow"
          type="range"
          min={decisionCount}
          max={example.bars.length}
          value={revealCount}
          onChange={(event) => setRevealCount(Number(event.target.value))}
          aria-label="Reveal historical candles"
        />
        <button className="btn btn-sm btn-primary" disabled={revealCount >= example.bars.length} onClick={() => setRevealCount((value) => Math.min(example.bars.length, value + 1))}>Next candle</button>
      </div>}
      {mode === "practice" && <div className="p-4" style={{ borderTop: "1px solid var(--border)" }}>
        <p className="text-sm font-semibold" style={{ color: "var(--ink)" }}>What is the disciplined decision at the frozen candle?</p>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mt-3">
          {(["call", "put", "wait", "reject"] as PracticeAnswer[]).map((choice) => <button
            key={choice}
            className={`btn ${answer === choice ? (correct ? "btn-primary" : "btn-ghost") : "btn-ghost"}`}
            onClick={() => setAnswer(choice)}
          >{choice === "call" ? "Enter CALL" : choice === "put" ? "Enter PUT" : choice === "wait" ? "Wait" : "Reject"}</button>)}
        </div>
        {answered && <div className="rounded-lg p-3 mt-3 text-sm" style={{ background: correct ? "var(--positive-bg)" : "var(--negative-bg)", color: "var(--ink)" }}>
          <strong>{correct ? "Correct." : "Review this one."}</strong> {example.coach.summary}
          <button className="btn btn-sm btn-ghost ml-2" onClick={() => setRevealCount(example.bars.length)}>Reveal outcome</button>
        </div>}
      </div>}
    </section>

    <aside className="card p-4 self-start">
      <div className="flex items-center gap-2"><BrainCircuit size={18} style={{ color: "var(--accent)" }} /><h3 className="font-semibold" style={{ color: "var(--ink)" }}>Coach Celo</h3></div>
      <p className="text-xs mt-1" style={{ color: "var(--ink-muted)" }}>Grounded in this recorded episode. No order authority.</p>
      <div className="rounded-xl p-4 mt-4 text-sm leading-relaxed" style={{ background: "var(--surface-raised)", color: "var(--ink)" }}>
        {coachMode === "prompt" ? (mode === "practice" && !answered
          ? "Classify only what is visible at the frozen candle: enter in the setup direction, wait for confirmation, or reject the setup."
          : example.coach.prompt) : coachMode === "facts" ? example.coach.summary : (
          example.outcome_observed_at
            ? `Recorded outcome: ${example.directional_move_pct == null ? example.outcome : `${example.directional_move_pct >= 0 ? "+" : ""}${example.directional_move_pct.toFixed(2)}% directional move`}.`
            : "This episode does not have a measured outcome yet. Coach Celo will not invent one."
        )}
      </div>
      <div className="flex flex-col gap-2 mt-3">
        <button className="btn btn-sm btn-ghost justify-start" onClick={() => setCoachMode("prompt")}>What should I identify?</button>
        <button className="btn btn-sm btn-ghost justify-start" disabled={mode === "practice" && !answered} onClick={() => setCoachMode("facts")}>Explain the recorded facts</button>
        <button className="btn btn-sm btn-ghost justify-start" disabled={mode === "practice" && !answered} onClick={() => setCoachMode("outcome")}>What happened afterward?</button>
      </div>
      <p className="text-[11px] mt-4" style={{ color: "var(--ink-faint)" }}>Source: {example.provenance}</p>
      {mode === "practice" && <p className="text-[11px] mt-2" style={{ color: "var(--ink-faint)" }}>Self-study score only; this is not a secure or proctored assessment.</p>}
    </aside>
  </div>;
}

export function LearningHub({ activeLessonIds, strategyCatalog }: { activeLessonIds: LessonId[]; strategyCatalog: ReviewedStrategyCatalogEntry[] }) {
  const { user } = useAuth();
  const progressOwner = String(user?.user_id ?? "anonymous");
  const [tab, setTab] = useState<HubTab>("learn");
  const { data: catalog } = useQuery({ queryKey: ["learning-catalog", progressOwner], queryFn: api.learning.catalog });
  const [strategyId, setStrategyId] = useState("");
  const [category, setCategory] = useState<LearningExampleCategory | "">("");

  const availableStrategies = catalog?.strategies ?? [];
  const selectedStrategyId = strategyId || availableStrategies[0]?.strategy_id || "";
  const { data: examplesData, isLoading } = useQuery({
    queryKey: ["learning-examples", progressOwner, selectedStrategyId, tab === "replay" ? category : ""],
    queryFn: () => api.learning.examples(selectedStrategyId, tab === "replay" ? category || undefined : undefined, 20),
    enabled: Boolean(selectedStrategyId) && tab !== "learn" && tab !== "progress",
  });
  const [exampleIndex, setExampleIndex] = useState(0);
  const examples = (examplesData?.examples ?? []).filter((item) => tab === "replay" || item.practice_eligible);
  const example = examples[exampleIndex % Math.max(examples.length, 1)];

  useEffect(() => setExampleIndex(0), [selectedStrategyId, category]);

  const completed = (() => {
    if (typeof localStorage === "undefined") return { correct: 0, review: 0 };
    let correct = 0; let review = 0;
    for (let index = 0; index < localStorage.length; index += 1) {
      const key = localStorage.key(index);
      if (!key?.startsWith(`celo-learning-example:${progressOwner}:`)) continue;
      if (localStorage.getItem(key) === "correct") correct += 1;
      else review += 1;
    }
    return { correct, review };
  })();

  return <div className="flex flex-col gap-4">
    <header className="card p-5" style={{ background: "linear-gradient(125deg, color-mix(in srgb, var(--accent) 12%, var(--surface)), var(--surface) 70%)" }}>
      <p className="text-xs uppercase tracking-[.16em] font-semibold" style={{ color: "var(--accent)" }}>Learning Hub</p>
      <h2 className="text-2xl font-bold mt-1" style={{ color: "var(--ink)" }}>Learn the rule. Practice the decision. Replay the outcome.</h2>
      <p className="text-sm mt-2" style={{ color: "var(--ink-muted)" }}>{catalog?.grounding ?? "Loading recorded evidence…"}</p>
      <div className="flex gap-2 mt-4 flex-wrap" role="tablist" aria-label="Learning Hub modes">
        {TABS.map(({ id, label, icon: Icon }) => <button key={id} className={`btn btn-sm ${tab === id ? "btn-primary" : "btn-ghost"}`} onClick={() => setTab(id)}><Icon size={15} />{label}</button>)}
      </div>
    </header>

    {tab === "learn" && <StrategyPlaybookExperience activeLessonIds={activeLessonIds} strategyCatalog={strategyCatalog} />}

    {(tab === "practice" || tab === "replay") && <>
      <div className="card p-3 flex gap-2 flex-wrap">
        <select className="input text-sm" value={selectedStrategyId} onChange={(event) => setStrategyId(event.target.value)}>
          {availableStrategies.map((strategy) => <option key={strategy.strategy_id} value={strategy.strategy_id}>{strategy.display_name} · {strategy.candidate_episodes} candidates</option>)}
        </select>
        {tab === "replay" && <select className="input text-sm" value={category} onChange={(event) => setCategory(event.target.value as LearningExampleCategory | "")}>
          <option value="">All example types</option>
          {Object.entries(CATEGORY_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select>}
        {examples.length > 0 && <button className="btn btn-sm btn-ghost" onClick={() => setExampleIndex((value) => (value + 1) % examples.length)}>Next example</button>}
      </div>
      {isLoading ? <div className="card p-8 text-center" style={{ color: "var(--ink-muted)" }}>Loading recorded examples…</div> : example ? <ExampleWorkspace key={`${example.example_id}:${tab}`} example={example} mode={tab} progressOwner={progressOwner} /> : <div className="card p-8 text-center" style={{ color: "var(--ink-muted)" }}>No chart-complete examples are available yet for this filter. Collection continues automatically as scanner candles and setup outcomes are recorded.</div>}
    </>}

    {tab === "progress" && <div className="grid gap-4" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))" }}>
      <div className="card p-5"><p className="text-xs uppercase tracking-wider" style={{ color: "var(--ink-muted)" }}>Your practice</p><p className="text-3xl font-bold mt-2" style={{ color: "var(--ink)" }}>{completed.correct}</p><p className="text-sm" style={{ color: "var(--ink-muted)" }}>correct decisions · {completed.review} marked for review</p></div>
      {availableStrategies.map((strategy) => <div className="card p-5" key={strategy.strategy_id}>
        <div className="flex justify-between gap-3"><div><p className="font-semibold" style={{ color: "var(--ink)" }}>{strategy.display_name}</p><p className="text-xs" style={{ color: "var(--ink-muted)" }}>Version {strategy.version} · candidate collection</p></div><strong style={{ color: "var(--accent)" }}>{strategy.candidate_episodes}</strong></div>
        <div className="h-2 rounded-full overflow-hidden mt-3" style={{ background: "var(--muted)" }}><div className="h-full" style={{ width: `${Math.min(100, strategy.candidate_episodes / strategy.target * 100)}%`, background: "var(--accent)" }} /></div>
        <p className="text-[11px] mt-2" style={{ color: "var(--ink-faint)" }}>Candidate episodes are screened for complete chart evidence when opened; they are not automatically published lessons.</p>
        <div className="grid grid-cols-2 gap-1 mt-3 text-[11px]" style={{ color: "var(--ink-muted)" }}>{Object.entries(strategy.category_targets).map(([key, target]) => <span key={key}>{CATEGORY_LABELS[key as LearningExampleCategory]}: {strategy.categories[key as LearningExampleCategory]}/{target}</span>)}</div>
      </div>)}
    </div>}
  </div>;
}
