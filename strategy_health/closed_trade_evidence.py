"""Read-only current-version trade-journal evidence, never research qualification."""
from collections import Counter, defaultdict
from datetime import datetime, timezone
import math

from config.strategy_catalog import REVIEWED_STRATEGIES


def _time(value):
    from zoneinfo import ZoneInfo
    parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo('America/New_York'))
    return parsed.astimezone(timezone.utc)


def summarize(rows, version):
    """Count a partially closed position once, only when all its legs close."""
    groups = defaultdict(list)
    for row in rows:
        groups[row['parent_trade_id'] or row['id']].append(row)
    excluded = Counter()
    completed = []
    for root_id, legs in groups.items():
        if not any(leg['id'] == root_id for leg in legs):
            excluded['missing_parent'] += 1
            continue
        versions = {leg['candidate_strategy_version'] for leg in legs}
        if versions != {version}:
            excluded['different_or_unknown_version'] += 1
            continue
        if any(leg['status'] != 'closed' for leg in legs):
            excluded['still_open'] += 1
            continue
        try:
            pnl = [float(leg['realized_pnl']) for leg in legs]
            starts = [_time(leg['entry_time']) for leg in legs]
            ends = [_time(leg['exit_time']) for leg in legs]
            if not all(math.isfinite(p) for p in pnl) or any(e < s for s, e in zip(starts, ends)):
                raise ValueError('Invalid closed result')
        except (ValueError, TypeError, OverflowError):
            excluded['incomplete_record'] += 1
            continue
        completed.append((min(starts), max(ends), sum(pnl)))
    profits = [r[2] for r in completed]
    gains = sum(p for p in profits if p > 0)
    losses = -sum(p for p in profits if p < 0)
    factor = round(gains / losses, 2) if losses else 'infinite' if gains else None
    from zoneinfo import ZoneInfo
    et = ZoneInfo('America/New_York')
    return dict(version=version, completed_trades=len(completed), profit_factor=factor,
                gross_profit=gains, gross_loss=losses,
                realized_pnl=round(sum(profits), 2) if profits else None,
                wins=sum(p > 0 for p in profits), exclusions=dict(excluded),
                first_entry_date=min(r[0] for r in completed).astimezone(et).date().isoformat() if completed else None,
                last_exit_date=max(r[1] for r in completed).astimezone(et).date().isoformat() if completed else None)


def build_closed_trade_evidence():
    from config import get_settings
    from database.connection import _conn_for_mode
    settings = get_settings()
    account = settings.get('active_broker_account_id')
    paper = bool(settings.get('paper_trading', True))
    mode = 'paper' if paper else 'live'
    result = dict(available=bool(account), account_mode=mode,
                  source='trade_journal', pnl_basis='recorded_realized_pnl', strategies=[])
    # No account identity means no safe account-scoped result, not all users.
    if not account:
        return result
    with _conn_for_mode(mode) as conn:
        rows = conn.execute('''
            SELECT t.id,t.parent_trade_id,t.strategy_id,t.ticker,t.status,
                   t.entry_time,t.exit_time,t.realized_pnl,
                   CASE WHEN json_valid(s.metadata_json)
                     THEN json_extract(s.metadata_json,'$.strategy_version') END AS candidate_strategy_version
            FROM trades t LEFT JOIN shadow_candidates s
              ON s.candidate_id=t.candidate_id AND s.broker_account_id=t.broker_account_id
              AND s.strategy_id=t.strategy_id AND s.ticker=t.ticker
            WHERE t.broker_account_id=? AND t.paper=?
            ORDER BY t.id
        ''', (account, int(paper))).fetchall()
    grouped = defaultdict(list)
    for row in rows:
        grouped[(row['strategy_id'], row['ticker'])].append(dict(row))
    for sid, rule in REVIEWED_STRATEGIES.items():
        if rule.observation_only:
            continue
        tickers = set(rule.tickers) | {ticker for strategy, ticker in grouped if strategy == sid}
        result['strategies'].append(dict(strategy_id=sid, version=rule.version,
            pairs=[dict(ticker=ticker, **summarize(grouped[(sid, ticker)], rule.version))
                   for ticker in sorted(tickers)]))
    return result
