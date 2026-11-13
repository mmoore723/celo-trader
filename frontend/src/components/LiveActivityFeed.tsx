import { useRef, useState } from 'react';
import { useBotStore, type LogEntry } from '../store/bot';
import { strategyName } from '../lib/strategyIdentity.js';

function text(value: unknown): string { return typeof value === 'string' ? value : ''; }
function eventTime(value: string | undefined) {
  if (!value) return 'Time not recorded';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleTimeString('en-US', { timeZone: 'America/New_York', hour: 'numeric', minute: '2-digit', second: '2-digit' }) + ' ET';
}
function isThinking(entry: LogEntry) {
  if (entry._separator) return false;
  const message = entry.message || '';
  if (/database initiali[sz]ed|AlpacaClient: routing|https?:\/\/|research_scan|execution_scan|research_bar_recovery|quote_capture|socket|websocket|GET \/api|POST \/api/i.test(message)) return false;
  return Boolean(entry.ticker || entry.strategy_id || entry.conditions || entry.checks || /\[[A-Z]{1,6}\]|setup|POSITION LIVE|holding|entry|exit|trade|signal|waiting|watching/i.test(message));
}
function checksFor(entry: LogEntry) {
  const values = entry.conditions ?? entry.checks;
  if (!Array.isArray(values)) return [];
  return values.filter((v) => v && typeof v === 'object').map((v) => ({
    name: text(v.name) || text(v.label) || 'Check',
    state: v.passed === true ? 'passed' : v.passed === false ? 'failed' :
      ['evaluating', 'pending'].includes(v.status) ? 'pending' : 'unknown',
    reason: text(v.reason) || text(v.detail) || 'No further explanation recorded.',
  }));
}
export function LiveActivityFeed() {
  const { logs, connected } = useBotStore();
  const [filter, setFilter] = useState('');
  const [paused, setPaused] = useState(false);
  const snapshot = useRef<LogEntry[]>([]);
  const keys = useRef(new WeakMap<LogEntry, number>());
  const counter = useRef(0);
  const scroller = useRef<HTMLDivElement>(null);
  if (!paused) snapshot.current = logs;
  const shown = snapshot.current.filter(isThinking).filter(e => `${e.ticker || ''} ${e.message} ${e.strategy_id || ''}`.toLowerCase().includes(filter.toLowerCase()));
  const pause = () => { snapshot.current = logs; setPaused(true); };
  return <section className="activity-feed" aria-label="Live Activity">
    <header><div><h2>Live Activity</h2><p>Thinking: setups, checks and position decisions.</p></div><span>{connected ? 'Connected' : 'Reconnecting'}</span></header>
    <div className="activity-tools"><input aria-label="Filter activity" placeholder="Ticker or strategy" value={filter} onChange={e => setFilter(e.target.value)} /><button onClick={() => { if (paused) { setPaused(false); scroller.current?.scrollTo(0, 0); } else pause(); }}>{paused ? 'Show newest updates' : 'Pause feed'}</button></div>
    <div className="activity-scroll" ref={scroller} onScroll={e => { if (!paused && e.currentTarget.scrollTop > 30) pause(); }}>
      {shown.map((entry, index) => {
        if (!keys.current.has(entry)) keys.current.set(entry, ++counter.current);
        const checks = checksFor(entry);
        const message = entry.message || text(entry.event) || 'Recorded update';
        const ticker = text(entry.ticker) || message.match(/\[([A-Z]{1,6})\]/)?.[1] || message.match(/ticker=([A-Z]+)/)?.[1] || 'System';
        const strategy = text(entry.strategy_id) || text(entry.strategy);
        const failed = checks.some(c => c.state === 'failed');
        const pending = checks.some(c => c.state === 'pending');
        const passed = checks.length > 0 && checks.every(c => c.state === 'passed');
        const state = failed ? 'failed' : pending ? 'pending' : passed ? 'passed' : 'unknown';
        const managing = /POSITION LIVE|Holding|In a trade/.test(message);
        const label = failed ? 'Check failed' : pending ? 'Evaluating' : passed ? 'Chart checks passed' : managing ? 'Managing position' : /no (entry |trade )?setup|continuing to watch/i.test(message) ? 'Scanning' : 'Recorded update';
        return <article key={keys.current.get(entry)} className={`activity-entry ${index === 0 ? 'latest' : ''}`} data-state={state}>
          {index === 0 && <div className="activity-latest">Latest entry</div>}
          <div className="activity-title"><strong>{ticker}</strong><span className="activity-state">{label}</span><time>{eventTime(entry.ts)}</time></div>
          {strategy && <div className="activity-strategy">{strategyName(strategy)}</div>}
          <p className="activity-message">{message.length > 220 ? message.slice(0, 217) + '…' : message}</p>
          {message.length > 220 && <details onToggle={e => { if (e.currentTarget.open && !paused) pause(); }}><summary>Full recorded explanation</summary><p className="activity-message">{message}</p></details>}
          {checks.length > 0 ? <div className="activity-checks">{checks.map((check, i) => <details key={i} data-state={check.state} onToggle={e => { if (e.currentTarget.open && !paused) pause(); }}><summary>{check.state === 'passed' ? '✓' : check.state === 'failed' ? '×' : check.state === 'pending' ? '◷' : '·'} {check.name}</summary><p>{check.reason}</p></details>)}</div> : <div className="activity-unrecorded">Individual strategy checks were not included in this update.</div>}
        </article>;
      })}
      {!shown.length && <p className="activity-empty">{filter ? 'No matching thinking updates.' : 'Waiting for the next setup or trading decision. Network messages are in the diagnostic log.'}</p>}
    </div>
    <footer>● Green: passed · ● Amber: evaluating · ● Red: failed · Gray: unrecorded<br/>Chart checks alone do not mean an order was approved.</footer>
  </section>;
}
