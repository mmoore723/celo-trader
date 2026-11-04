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
    <p className="text-sm">Version {version}. Learning only; opening this page does not change trading.</p>
    {selection && tickers.length > 1 ? <label className="block text-sm">Account rules and practice example<select aria-label="Example ticker" className="input ml-2" value={ticker} onChange={e => setContextTicker(e.target.value)}>{tickers.map(t => <option key={t}>{t}</option>)}</select><span className="block text-xs">Same strategy. Selected exit policies and actual trade records can differ by ticker.</span></label> : <p className="text-xs">Example and configured policy: {ticker}</p>}
    <nav className="flex flex-wrap gap-2" aria-label="Strategy learning resources">{['lesson','reference','practice'].map(item => selection ? <button key={item} className={`btn btn-sm ${view === item ? 'btn-primary' : 'btn-ghost'}`} onClick={() => setLessonView(item)}>{item[0].toUpperCase()+item.slice(1)}</button> : <Link key={item} className={`btn btn-sm ${view === item ? 'btn-primary' : 'btn-ghost'}`} to={learningLink(strategy,ticker,version,item)}>{item[0].toUpperCase()+item.slice(1)}</Link>)}</nav>
    {isPending ? <p role="status">Loading the strategy reference...</p> : isError ? <p role="alert">This version’s learning reference could not load. Return to Settings to check the current version, or try again later.</p> : data && <>
      {view === 'practice' ? <div className="space-y-4"><TradePractice key={`${strategy}:${ticker}:${version}`} strategy={strategy} ticker={ticker} version={version}/><details><summary className="cursor-pointer">Scanner chart practice (observed setups, not necessarily executed trades)</summary><SecurePractice key={`${strategy}:${ticker}:${version}`} strategyId={strategy} ticker={ticker} version={version} progressOwner={String(user?.user_id ?? '')} /></details></div> : <>
        {view === 'lesson' && lessons[data.source] && <div className="space-y-3"><p className="text-sm font-semibold">Chart lesson: source strategy example. Read the version-specific rules below for {ticker} / {version}; the example is not a replay of your selected exit policy.</p><StrategyPlaybookExperience key={data.source} activeLessonIds={[lessons[data.source]]} strategyCatalog={[]} /></div>}
        {view === 'lesson' && <VersionRuleWalkthrough key={`${strategy}:${ticker}:${version}:${data.policy_version}`} version={version} steps={data.steps} exit={data.exit} selectedPolicy={data.selected_policy} />}
        {view === 'lesson' && !lessons[data.source] && <p className="text-sm">This variation has a written rule lesson, but no dedicated annotated price-chart lesson yet. Practice can show recorded scanner charts when available. Another variation’s chart is not being passed off as this one.</p>}
        <h3 className="font-semibold">{view === 'reference' ? 'Entry checklist' : 'How this setup works'}</h3>
        {data.steps.length ? <ol className="list-decimal pl-5 space-y-3 text-sm">{data.steps.map(step => <li key={step}>{step}</li>)}</ol> : <p className="text-sm">A step-by-step entry lesson has not been published for this version. The native exit reference and research evidence are below. No substitute rules are being shown.</p>}
        <h3 className="font-semibold">{data.selected_policy ? 'Your selected exit' : 'Research baseline exit reference'}</h3><p className="text-sm">{data.exit}</p>
        <p className="text-xs">{data.selected_policy ? `Policy: ${data.policy_version}.` : 'Research reference, not a statement of an open position’s current exit.'} Existing positions keep their entry-time policy. Indicators do not guarantee an outcome.</p>
        <details><summary className="cursor-pointer">Research evidence</summary><p className="text-sm mt-2">{data.evidence}</p></details>
        <section className="rounded-lg border p-4 space-y-2" aria-label="Protection and position sizing">
          <h3 className="font-semibold">Protection and position sizing</h3>
          <p className="text-sm">A stop is the rule that invalidates the trade. Check the exit reference above for its exact trigger and candle timing. A timed exit is not a price stop. A drawn support line does not become an active stop unless that version explicitly uses it.</p>
          <p className="text-sm">For the bot’s reviewed strategies, sizing budgets the full option premium: contracts = floor(account equity × risk fraction ÷ (planned premium × 100)). The premium-spend cap, available buying power and execution checks can reduce or reject that size.</p>
          <p className="text-sm">Teaching example, not your account settings: $10,000 × 2% = $200 budget. At a $2 premium, one contract costs $200 before fees. Two contracts cost $400 and exceed that example budget.</p>
          <p className="text-sm">If a strategy has an actual premium stop, risk per contract is (entry premium − stop premium) × 100, plus costs. Do not use that smaller denominator for a stock-chart stop: it does not guarantee the option’s exit premium. Stops can slip.</p>
        </section>
        <Link to="/playbooks?tab=glossary" className="btn btn-sm btn-ghost">Trading glossary</Link>
      </>}
    </>}
  </section>;
}
