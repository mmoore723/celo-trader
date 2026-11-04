import { useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { request, type ReviewedStrategyCatalogEntry } from '../../lib/api';
import { learningLink } from '../../lib/learningLinks';
import { useAuth } from '../../contexts/AuthContext';
import { SecurePractice } from './LearningHub';
import { TradePractice } from './TradePractice';
import { VersionRuleWalkthrough } from './VersionRuleWalkthrough';
import { StrategyPlaybookExperience, type LessonId } from '../playbooks/StrategyPlaybookExperience';

type Guide = { name: string; steps: string[]; exit: string; evidence: string; policy_version: string; source: string; selected_policy: boolean };

export function PairLearning({strategyCatalog, selection}: {strategyCatalog: ReviewedStrategyCatalogEntry[]; selection?: {strategy:string;ticker:string;version:string}}) {
  const [params] = useSearchParams();
  const { user } = useAuth();
  const [contextTicker, setContextTicker] = useState('');
  const [lessonView, setLessonView] = useState('lesson');
  const strategy = selection?.strategy ?? params.get('strategy') ?? '';
  const ticker = selection ? contextTicker || selection.ticker : params.get('ticker') ?? '';
  const version = selection?.version ?? params.get('version') ?? '';
  const view = selection ? lessonView : params.get('view') ?? 'lesson';
  const tickers = strategyCatalog.find(s => s.strategy_id === strategy && s.version === version)?.trading_tickers ?? [];
  const lessons: Record<string,LessonId> = {V2_ORB_PULLBACK:'v2_orb',V2_SPY_TREND_CONT:'v2_trend',V2_SPY_AFTERNOON_FVG:'v2_spy_fvg',V2_TSLA_TWO_LEG_TREND_PULLBACK:'v2_two_leg',V2_FAILED_OR_BREAK_VWAP_REVERSION:'v2_recovery'};
  const { data, isPending, isError } = useQuery({
    queryKey: ['learning-guide', user?.user_id, strategy, ticker, version],
    queryFn: () => request<Guide>(`/api/learning/guide?${new URLSearchParams({ strategy_id: strategy, ticker, version })}`),
    retry: false,
  });
  return <section className="card p-5 space-y-4">
    {!selection && <Link to="/playbooks" className="text-sm">All learning resources</Link>}
    <h2 className="text-xl font-semibold">{data?.name ?? 'Strategy learning'}</h2>
    <p className="text-sm">Version {version}</p>
    {selection && tickers.length > 1 ? <label className="block text-sm">Example ticker<select aria-label="Example ticker" className="input ml-2" value={ticker} onChange={e => setContextTicker(e.target.value)}>{tickers.map(t => <option key={t}>{t}</option>)}</select><span className="block text-xs">Your trade examples and saved exit settings may differ by ticker.</span></label> : <p className="text-xs">Chart example: {ticker}</p>}
    <nav className="flex flex-wrap gap-2" aria-label="Strategy learning resources">{['lesson','reference','practice'].map(item => selection ? <button key={item} className={`btn btn-sm ${view === item ? 'btn-primary' : 'btn-ghost'}`} onClick={() => setLessonView(item)}>{item[0].toUpperCase()+item.slice(1)}</button> : <Link key={item} className={`btn btn-sm ${view === item ? 'btn-primary' : 'btn-ghost'}`} to={learningLink(strategy,ticker,version,item)}>{item[0].toUpperCase()+item.slice(1)}</Link>)}</nav>
    {isPending ? <p role="status">Loading your lesson...</p> : isError ? <p role="alert">We couldn’t load this lesson. Please refresh and try again.</p> : data && <>
      {view === 'practice' ? <div className="space-y-4"><TradePractice key={`${strategy}:${ticker}:${version}`} strategy={strategy} ticker={ticker} version={version}/><details><summary className="cursor-pointer">Practice with spotted setups</summary><p className="text-xs my-2">These are setups the scanner spotted, not necessarily trades the bot entered.</p><SecurePractice key={`${strategy}:${ticker}:${version}`} strategyId={strategy} ticker={ticker} version={version} progressOwner={String(user?.user_id ?? '')} /></details></div> : <>
        {view === 'lesson' && lessons[data.source] && <div className="space-y-3"><p className="text-sm font-semibold">Follow the chart step by step. It teaches the original rules; your saved exit may differ.</p><StrategyPlaybookExperience key={data.source} activeLessonIds={[lessons[data.source]]} strategyCatalog={[]} /></div>}
        {view === 'lesson' && <VersionRuleWalkthrough key={`${strategy}:${ticker}:${version}:${data.policy_version}`} version={version} steps={data.steps} exit={data.exit} selectedPolicy={data.selected_policy} />}
        {view === 'lesson' && !lessons[data.source] && <p className="text-sm">The chart lesson for this variation is not ready yet. You can still learn its checklist below.</p>}
        {view === 'reference' && <div className="space-y-3">
          <h3 className="font-semibold">Before you enter</h3>
          {data.steps.length ? <ol className="list-decimal pl-5 space-y-2 text-sm">{data.steps.map(step => <li key={step}>{step}</li>)}</ol> : <p>The entry checklist is not ready yet.</p>}
          <h3 className="font-semibold">{data.selected_policy ? 'Your chosen exit' : 'Exit taught in this example'}</h3>
          <p className="text-sm">{data.exit}</p>
          <p className="text-xs">Check your saved settings for the exit used by your bot. Open trades keep their original rules.</p>
        </div>}
        <Link to="/playbooks?tab=glossary" className="btn btn-sm btn-ghost">Trading glossary</Link>
      </>}
    </>}
  </section>;
}
