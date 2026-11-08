import { lazy, Suspense, useState } from 'react';
const Results = lazy(() => import('./ScannerOpportunities').then(m => ({ default: m.ScannerOpportunities })));
const Lab = lazy(() => import('./ExitLab').then(m => ({ default: m.ExitLab })));
const Coverage = lazy(() => import('./CaptureCoverage').then(m => ({ default: m.CaptureCoverage })));

export function Research() {
  const [tab, setTab] = useState<'results' | 'exits' | 'coverage'>('results');
  return <div className="page-container space-y-4"><nav className="flex gap-2" aria-label="Research subtabs"><button className={`btn btn-sm ${tab === 'results' ? 'btn-primary' : 'btn-ghost'}`} aria-pressed={tab === 'results'} onClick={() => setTab('results')}>Research Results</button><button className={`btn btn-sm ${tab === 'exits' ? 'btn-primary' : 'btn-ghost'}`} aria-pressed={tab === 'exits'} onClick={() => setTab('exits')}>Exit Lab</button><button className={`btn btn-sm ${tab === 'coverage' ? 'btn-primary' : 'btn-ghost'}`} aria-pressed={tab === 'coverage'} onClick={() => setTab('coverage')}>Data Coverage</button></nav><Suspense fallback={<p role="status">Loading...</p>}>{tab === 'results' ? <Results view="research" embedded /> : tab === 'exits' ? <Lab /> : <Coverage />}</Suspense></div>;
}
