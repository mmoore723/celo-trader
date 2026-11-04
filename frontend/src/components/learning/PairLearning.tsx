import { Link, useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { request, type ReviewedStrategyCatalogEntry } from '../../lib/api';
import { learningLink } from '../../lib/learningLinks';
import { useAuth } from '../../contexts/AuthContext';
import { SecurePractice } from './LearningHub';
import { TradePractice } from './TradePractice';
import { StrategyPlaybookExperience, type LessonId } from '../playbooks/StrategyPlaybookExperience';

type Guide = { name: string; steps: string[]; exit: string; evidence: string; policy_version: string; source: string; selected_policy: boolean };

export function PairLearning({strategyCatalog}: {strategyCatalog: ReviewedStrategyCatalogEntry[]}) {
  const [params] = useSearchParams();
  const { user } = useAuth();
  const strategy = params.get('strategy') ?? '';
  const ticker = params.get('ticker') ?? '';
  const version = params.get('version') ?? '';
  const view = params.get('view') ?? 'lesson';
  const lessons: Record<string,LessonId> = {V2_ORB_PULLBACK:'v2_orb',V2_SPY_TREND_CONT:'v2_trend',V2_SPY_AFTERNOON_FVG:'v2_spy_fvg',V2_TSLA_TWO_LEG_TREND_PULLBACK:'v2_two_leg',V2_FAILED_OR_BREAK_VWAP_REVERSION:'v2_recovery'};
  const { data, isPending, isError } = useQuery({
    queryKey: ['learning-guide', user?.user_id, strategy, ticker, version],
    queryFn: () => request<Guide>(`/api/learning/guide?${new URLSearchParams({ strategy_id: strategy, ticker, version })}`),
    retry: false,
  });
  return <section className="card p-5 space-y-4">
    <Link to="/playbooks" className="text-sm">All learning resources</Link>
    <h2 className="text-xl font-semibold">{ticker} · {data?.name ?? 'Strategy learning'}</h2>
    <p className="text-sm">Version {version}. Learning only; opening this page does not change trading.</p>
    <nav className="flex flex-wrap gap-2" aria-label="Pair learning resources">{['lesson','reference','practice'].map(item => <Link key={item} className={`btn btn-sm ${view === item ? 'btn-primary' : 'btn-ghost'}`} to={learningLink(strategy,ticker,version,item)}>{item[0].toUpperCase()+item.slice(1)}</Link>)}</nav>
    {isPending ? <p role="status">Loading the strategy reference...</p> : isError ? <p role="alert">This version’s learning reference could not load. Return to Settings to check the current version, or try again later.</p> : data && <>
      {view === 'practice' ? <div className="space-y-4"><TradePractice key={`${strategy}:${ticker}:${version}`} strategy={strategy} ticker={ticker} version={version}/><details><summary className="cursor-pointer">Scanner chart practice (observed setups, not necessarily executed trades)</summary><SecurePractice key={`${strategy}:${ticker}:${version}`} strategyId={strategy} ticker={ticker} version={version} progressOwner={String(user?.user_id ?? '')} /></details></div> : <>
        <h3 className="font-semibold">{view === 'reference' ? 'Entry checklist' : 'How this setup works'}</h3>
        {data.steps.length ? <ol className="list-decimal pl-5 space-y-3 text-sm">{data.steps.map(step => <li key={step}>{step}</li>)}</ol> : <p className="text-sm">A step-by-step entry lesson has not been published for this version. The native exit reference and research evidence are below. No substitute rules are being shown.</p>}
        <h3 className="font-semibold">{data.selected_policy ? 'Your selected exit' : 'Research baseline exit reference'}</h3><p className="text-sm">{data.exit}</p>
        <p className="text-xs">{data.selected_policy ? `Policy: ${data.policy_version}.` : 'Research reference, not a statement of an open position’s current exit.'} Existing positions keep their entry-time policy. Indicators do not guarantee an outcome.</p>
        <details><summary className="cursor-pointer">Research evidence</summary><p className="text-sm mt-2">{data.evidence}</p></details>
        {view === 'lesson' && lessons[strategy] && <details><summary className="cursor-pointer">Open visual walkthrough</summary><StrategyPlaybookExperience activeLessonIds={[lessons[strategy]]} strategyCatalog={strategyCatalog} /></details>}
        <Link to="/playbooks?tab=glossary" className="btn btn-sm btn-ghost">Trading glossary</Link>
      </>}
    </>}
  </section>;
}
