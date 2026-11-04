import { useCallback, useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { BookOpen, BrainCircuit, GraduationCap, RotateCcw, Trophy } from "lucide-react";

import { api, type LearningExample, type LearningExampleCategory, type LearningPracticeStart, type ReviewedStrategyCatalogEntry } from "../../lib/api";
import { scoreLearningAnswer, type LearningPracticeAnswer } from "../../lib/learningSemantics.js";
import { VisualLessonStage } from "./VisualLessonStage";
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
  const [coachMode, setCoachMode] = useState<"prompt" | "facts" | "outcome">("prompt");
  const answered = answer !== null;
  const correct = answer ? scoreLearningAnswer(example.category, example.direction, answer) : false;

  useEffect(() => {
    setAnswer(null);
    setCoachMode("prompt");
  }, [example.example_id, decisionCount]);

  useEffect(() => {
    if (answered) localStorage.setItem(progressKey(progressOwner, example.example_id), correct ? "correct" : "review");
  }, [answered, correct, example.example_id, progressOwner]);

  return <div className="grid gap-4" style={{ gridTemplateColumns: "minmax(0, 1.7fr) minmax(270px, .8fr)" }}>
    <section className="card overflow-hidden">
      <div className="px-4 py-3 flex items-center justify-between gap-3 flex-wrap" style={{ borderBottom: "1px solid var(--border)" }}>
        <div>
          <p className="text-sm font-semibold" style={{ color: "var(--ink)" }}>{example.ticker} · {example.strategy_id}</p>
          <p className="text-xs" style={{ color: "var(--ink-muted)" }}>{new Date(example.observed_at).toLocaleString()} · v{example.strategy_version}</p>
        </div>
        <span className="badge badge-blue">{mode === "practice" && !answered ? "Frozen decision" : CATEGORY_LABELS[example.category]}</span>
      </div>
      <VisualLessonStage example={example} unlocked={mode === "replay" || answered} />
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
          <span className="ml-2">Use Coach Celo’s visual steps above to review the evidence.</span>
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

export function SecurePractice({ strategyId, progressOwner, ticker, version }: { strategyId: string; progressOwner: string; ticker?: string; version?: string }) {
  const [session, setSession] = useState<LearningPracticeStart | null>(null);
  const [result, setResult] = useState<{ correct: boolean; example: LearningExample } | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [question, setQuestion] = useState("");
  const [coachAnswer, setCoachAnswer] = useState("");

  const load = useCallback(async () => {
    setLoading(true); setError(""); setResult(null); setCoachAnswer("");
    try {
      const response = await api.learning.startPractice(strategyId, ticker, version);
      if ('status' in response) { setError(response.message); setSession(null); }
      else setSession(response);
    }
    catch { setError("Practice could not load. Try again, or return to the lesson."); setSession(null); }
    finally { setLoading(false); }
  }, [strategyId, ticker, version]);
  useEffect(() => { void load(); }, [load]);

  const answer = async (choice: PracticeAnswer) => {
    if (!session || result) return;
    try {
      const response = await api.learning.answerPractice(session.session_id, choice);
      setResult(response);
      localStorage.setItem(progressKey(progressOwner, response.example.example_id), response.correct ? "correct" : "review");
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Answer could not be scored"); }
  };
  const ask = async () => {
    if (!result || !question.trim()) return;
    try { setCoachAnswer((await api.learning.askCoach(result.example.example_id, session!.session_id, question.trim())).answer); }
    catch (reason) { setCoachAnswer(reason instanceof Error ? reason.message : "Coach unavailable"); }
  };
  if (loading) return <div className="card p-8 text-center">Preparing a secure practice session…</div>;
  if (!session) return <div className="card p-8 text-center"><p>{error || "No practice lesson is available yet."}</p><button className="btn btn-sm btn-ghost mt-3" onClick={() => void load()}>Try again</button></div>;
  const shown = result?.example ?? session.example;
  return <div className="grid gap-4" style={{ gridTemplateColumns: "minmax(0, 1.7fr) minmax(270px, .8fr)" }}>
    <section className="card overflow-hidden">
      <div className="px-4 py-3"><strong>{shown.ticker} · {shown.strategy_id}</strong><p className="text-xs" style={{ color: "var(--ink-muted)" }}>Server-frozen evidence · v{shown.strategy_version}</p></div>
      <VisualLessonStage example={shown} unlocked={Boolean(result)} />
      <div className="p-4"><p className="text-sm font-semibold">{result ? result.example.coach.summary : session.example.prompt}</p>
        {!result && <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mt-3">{(["call", "put", "wait", "reject"] as PracticeAnswer[]).map((choice) => <button className="btn btn-ghost" key={choice} onClick={() => void answer(choice)}>{choice === "call" ? "Enter CALL" : choice === "put" ? "Enter PUT" : choice[0].toUpperCase()+choice.slice(1)}</button>)}</div>}
        {result && <div className="mt-3"><strong>{result.correct ? "Correct." : "Review this one."}</strong><button className="btn btn-sm btn-ghost ml-2" onClick={() => void load()}>Next secure example</button></div>}
        {error && <p className="text-sm mt-2" style={{ color: "var(--negative)" }}>{error}</p>}
      </div>
    </section>
    <aside className="card p-4 self-start"><h3 className="font-semibold">Coach Celo</h3><p className="text-xs mt-1" style={{ color: "var(--ink-muted)" }}>Episode-grounded answers; no external data transfer or order authority.</p>
      {result ? <><textarea className="input w-full mt-4" rows={3} maxLength={500} value={question} onChange={(event) => setQuestion(event.target.value)} placeholder="Ask why, what happened, or which rule applies…" /><button className="btn btn-sm btn-primary mt-2" onClick={() => void ask()}>Ask Coach</button>{coachAnswer && <p className="text-sm mt-3 rounded-lg p-3" style={{ background: "var(--surface-raised)" }}>{coachAnswer}</p>}</> : <p className="text-sm mt-4">Answer first; the server has not sent the category, outcome, coach summary, or future candles.</p>}
    </aside>
  </div>;
}

export function LearningHub({ activeLessonIds, strategyCatalog }: { activeLessonIds: LessonId[]; strategyCatalog: ReviewedStrategyCatalogEntry[] }) {
  const { user } = useAuth();
  const progressOwner = String(user?.user_id ?? "anonymous");
  const [tab, setTab] = useState<HubTab>("learn");
  const { data: catalog } = useQuery({ queryKey: ["learning-catalog", progressOwner], queryFn: api.learning.catalog });
  const { data: ranker } = useQuery({ queryKey: ["learning-ranker", progressOwner], queryFn: api.learning.rankerStatus });
  const [strategyId, setStrategyId] = useState("");
  const [category, setCategory] = useState<LearningExampleCategory | "">("");

  const availableStrategies = catalog?.strategies ?? [];
  const selectedStrategyId = strategyId || availableStrategies[0]?.strategy_id || "";
  const { data: examplesData, isLoading } = useQuery({
    queryKey: ["learning-examples", progressOwner, selectedStrategyId, tab === "replay" ? category : ""],
    queryFn: () => api.learning.examples(selectedStrategyId, tab === "replay" ? category || undefined : undefined, 20),
    enabled: Boolean(selectedStrategyId) && tab === "replay",
  });
  const [exampleIndex, setExampleIndex] = useState(0);
  const examples = examplesData?.examples ?? [];
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
          {availableStrategies.map((strategy) => <option key={strategy.strategy_id} value={strategy.strategy_id}>{strategy.display_name} · {strategy.curated_examples} reviewed examples</option>)}
        </select>
        {tab === "replay" && <select className="input text-sm" value={category} onChange={(event) => setCategory(event.target.value as LearningExampleCategory | "")}>
          <option value="">All example types</option>
          {Object.entries(CATEGORY_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select>}
        {examples.length > 0 && <button className="btn btn-sm btn-ghost" onClick={() => setExampleIndex((value) => (value + 1) % examples.length)}>Next example</button>}
      </div>
      {tab === "practice" ? <SecurePractice key={`${progressOwner}:${selectedStrategyId}`} strategyId={selectedStrategyId} progressOwner={progressOwner} /> : isLoading ? <div className="card p-8 text-center" style={{ color: "var(--ink-muted)" }}>Loading recorded examples…</div> : example ? <ExampleWorkspace key={`${example.example_id}:${tab}`} example={example} mode={tab} progressOwner={progressOwner} /> : <div className="card p-8 text-center" style={{ color: "var(--ink-muted)" }}>No chart-complete examples are available yet for this filter. Collection continues automatically as scanner candles and setup outcomes are recorded.</div>}
    </>}

    {tab === "progress" && <div className="grid gap-4" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))" }}>
      <div className="card p-5"><p className="text-xs uppercase tracking-wider" style={{ color: "var(--ink-muted)" }}>Your practice</p><p className="text-3xl font-bold mt-2" style={{ color: "var(--ink)" }}>{completed.correct}</p><p className="text-sm" style={{ color: "var(--ink-muted)" }}>correct decisions · {completed.review} marked for review</p></div>
      <div className="card p-5"><p className="text-xs uppercase tracking-wider" style={{ color: "var(--ink-muted)" }}>ML shadow ranker</p><p className="text-3xl font-bold mt-2" style={{ color: "var(--ink)" }}>{ranker?.usable_episodes ?? 0}/1,000</p><p className="text-sm" style={{ color: "var(--ink-muted)" }}>{ranker?.status === "shadow_active" ? "Chronologically qualified · shadow predictions only" : ranker?.status === "trained_not_qualified" ? "Trained, but holdout quality did not qualify" : "Collecting independent chart-complete outcomes"} · no order authority</p></div>
      {availableStrategies.map((strategy) => <div className="card p-5" key={strategy.strategy_id}>
        <div className="flex justify-between gap-3"><div><p className="font-semibold" style={{ color: "var(--ink)" }}>{strategy.display_name}</p><p className="text-xs" style={{ color: "var(--ink-muted)" }}>Version {strategy.version} · reviewed examples, not your score</p></div><strong style={{ color: "var(--accent)" }}>{strategy.curated_examples} available</strong></div>
        {!strategy.curated_examples && <p className="text-sm mt-2">This library is empty. No examples have passed its version and chart-coverage checks.</p>}
        <div className="h-2 rounded-full overflow-hidden mt-3" style={{ background: "var(--muted)" }}><div className="h-full" style={{ width: `${Math.min(100, strategy.curated_examples / strategy.target * 100)}%`, background: "var(--accent)" }} /></div>
        <p className="text-[11px] mt-2" style={{ color: "var(--ink-faint)" }}>Only version-matched, chart-complete, independent recorded episodes count.</p>
        <div className="grid grid-cols-2 gap-1 mt-3 text-[11px]" style={{ color: "var(--ink-muted)" }}>{Object.entries(strategy.category_targets).map(([key, target]) => <span key={key}>{CATEGORY_LABELS[key as LearningExampleCategory]}: {strategy.categories[key as LearningExampleCategory]}/{target}</span>)}</div>
      </div>)}
    </div>}
  </div>;
}
