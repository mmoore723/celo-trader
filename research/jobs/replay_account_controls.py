"""Chronological portfolio ledger, not a broker-fill or profitability forecast.

Uses the selected observed trade opportunities together, not isolated returns.
Production sizing is called directly under a read-only settings snapshot.
Cash-reuse and next-business-day settlement are explicit alternative models.
Missing fresh marks and unresolved emergency exits are surfaced, never filled in.
"""
from bisect import bisect_right
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_FLOOR
from zoneinfo import ZoneInfo

from auth.context import set_current_user
from config.research_snapshot import research_settings_snapshot
from config import COMMISSION_PER_CONTRACT
from risk.manager import RiskManager
from risk.entry_capacity import available_entry_quantity

D = lambda value: Decimal(str(value))
ET = ZoneInfo('America/New_York')


def timestamp(value):
    dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    return dt.replace(tzinfo=ET) if dt.tzinfo is None else dt.astimezone(ET)


def next_business_day(day):
    day += timedelta(days=1)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return day


def replay(trades, quotes, settings, *, initial=5000, corrected=True,
           settled_only=True, fee_per_side=.65, friction_per_side=0,
           settlement_sessions=None, ticker_routing=False, routing_paper=True):
    """Fees/friction are modeled, not billed fees. No leveraged buying power.

    Without explicit settlement sessions, skips weekends only. An explicit
    calendar must cover the last exit and may conservatively postpone
    receipts to the next observed market session. Never invent missing sessions.
    Unsettled receipts remain equity, not spending power. Entries with a contract
    identity use the production capacity gate. Fills remain instantaneous and
    hypothetical, not a simulation of order latency or account margin rules.
    ticker_routing requires explicit ticker identities and reproduces the
    production one-open-ticker and 10-minute profitable-close gates. The
    cooldown uses journal P&L (gross for paper, configured commission for live),
    not the extra cost assumptions used to stress the research account.
    This does not reconstruct scheduler state or historical entry eligibility.
    """
    if len({t['id'] for t in trades}) != len(trades):
        raise ValueError('Duplicate trades')
    if ticker_routing and any(not isinstance(t.get('ticker'), str) or
                             not t['ticker'].strip() for t in trades):
        raise ValueError('Ticker routing requires an explicit ticker on every trade')
    cash = D(initial)
    fee, friction = D(fee_per_side), D(friction_per_side)
    if cash <= 0 or min(fee, friction) < 0:
        raise ValueError('Invalid capital/costs')
    sessions = None
    if settlement_sessions is not None:
        sessions = [date.fromisoformat(s) for s in settlement_sessions]
        if sessions != sorted(set(sessions)):
            raise ValueError('Settlement sessions must be unique and ordered')
        if settled_only and trades and (not sessions or sessions[-1] < max(
                timestamp(t['exit_time']).date() for t in trades)):
            raise ValueError('Settlement calendar must cover all exits')

    def settles_on(day):
        if sessions is None:
            return next_business_day(day)
        index = bisect_right(sessions, day)
        # Receipts after the last supplied session stay unsettled. date.max is
        # an internal sentinel, not a claimed settlement date or spending power.
        return sessions[index] if index < len(sessions) else date.max
    events, by_id = [], {t['id']: t for t in trades}
    for t in trades:
        start, end = timestamp(t['entry_time']), timestamp(t['exit_time'])
        if end <= start or min(D(t['entry_price']), D(t['exit_price'])) <= 0:
            raise ValueError('Invalid price or trade interval')
        events += [(start, 2, t['id'], 'entry', t), (end, 1, t['id'], 'exit', t)]
    for q in quotes:
        if q['trade_id'] not in by_id or q.get('bid') is None or D(q['bid']) < 0:
            continue
        events.append((timestamp(q['observed_at']), 0, q['trade_id'], 'mark', q))
    events.sort(key=lambda e: e[:3])
    opened, pending, decisions, closed, daily = {}, [], [], [], {}
    win_cooldowns = {}
    day = None
    day_open = peak = cash
    realized = D(0)
    drawdown = D(0)
    max_locked = D(0)
    max_open = 0
    halt_until = None
    halt_is_hard = False
    unresolved_halts, stale_marks = set(), 0

    def equity():
        return cash + sum((amount for _, amount in pending), D(0)) + sum(
            (p['mark'] * 100 * p['qty'] for p in opened.values()), D(0))

    set_current_user('account-replay', 'account-replay', False)
    with research_settings_snapshot('account-replay', settings):
        risk = RiskManager(float(cash))
        for now, _, tid, kind, item in events:
            if day != now.date():
                if day is not None:
                    daily[str(day)] = float(equity() - day_open)
                day = now.date()
                win_cooldowns.clear()
                available = [(date, amount) for date, amount in pending if date <= day]
                cash += sum((amount for _, amount in available), D(0))
                pending = [(date, amount) for date, amount in pending if date > day]
                day_open, realized = equity(), D(0)
            if kind == 'mark' and tid in opened:
                opened[tid].update(mark=max(D(0), D(item['bid']) - friction), marked_at=now)
            elif kind == 'exit' and tid in opened:
                p = opened.pop(tid)
                proceeds = max(D(0), D(item['exit_price']) - friction) * 100 * p['qty'] - fee * p['qty']
                pnl = proceeds - p['debit']
                if settled_only:
                    pending.append((settles_on(day), proceeds))
                else:
                    cash += proceeds
                realized += pnl
                journal_pnl = (max(D(0), D(item['exit_price']) - friction) - p['ask']) * 100 * p['qty']
                if not routing_paper:
                    journal_pnl -= D(COMMISSION_PER_CONTRACT) * 2 * p['qty']
                if ticker_routing and journal_pnl > 0:
                    win_cooldowns[p['ticker']] = now + timedelta(minutes=10)
                closed.append({'id': tid, 'quantity': p['qty'], 'pnl': float(pnl),
                               'routing_pnl': float(journal_pnl), 'ticker': p['ticker'],
                               'exit': now.isoformat()})
            current = equity()
            hard = min(current - day_open, realized) <= -day_open * D(settings['daily_loss_hard_cap_pct']) / 100
            soft = realized <= -day_open * D(settings['max_daily_loss_pct'])
            if hard or soft:
                expiry = now + timedelta(hours=float(settings.get('kill_lock_hours', 24))) if hard else (
                    now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
                if halt_until is None or now >= halt_until:
                    halt_until = expiry
                    halt_is_hard = hard
                elif hard and not halt_is_hard:
                    halt_until = max(halt_until, expiry)
                    halt_is_hard = True
                unresolved_halts.update(opened)
            if kind == 'entry':
                stale_marks += sum((now - p['marked_at']).total_seconds() > 120 for p in opened.values())
                ask = D(item['entry_price']) + friction
                if corrected:
                    qty = risk.calculate_contracts(risk.slippage_adjusted_entry(float(ask)),
                                                    float(current), strategy_id=item['strategy_id'])
                else:
                    qty = int(item['contracts'])
                if item.get('entry_size') is not None:
                    qty = min(qty, int(D(item['entry_size']).to_integral_value(rounding=ROUND_FLOOR)))
                reason = None
                ticker = item.get('ticker', '').strip().upper()
                if halt_until and now < halt_until:
                    reason = 'daily_loss_halt'
                elif ticker_routing and any(p['ticker'] == ticker for p in opened.values()):
                    reason = 'ticker_already_open'
                elif ticker_routing and now < win_cooldowns.get(ticker, now):
                    reason = 'ticker_post_win_cooldown'
                elif item.get('contract_symbol') and any(
                        p.get('contract_symbol') == item['contract_symbol'] for p in opened.values()):
                    reason = 'contract_already_open_or_pending'
                elif len(opened) >= int(settings.get('max_concurrent_positions', 2)):
                    reason = 'position_limit'
                elif qty < 1:
                    reason = 'existing_risk_budget'
                else:
                    affordable = int((cash / (ask * 100 + fee)).to_integral_value(rounding=ROUND_FLOOR))
                    qty = min(qty, affordable)
                    if qty < 1:
                        reason = 'settled_cash' if settled_only else 'cash_buying_power'
                if reason is None and item.get('contract_symbol'):
                    # The same pure capacity gate as production. No broker calls.
                    qty, reason = available_entry_quantity(
                        account={'equity': float(current), 'cash': float(cash),
                                 'options_buying_power': float(cash)},
                        positions=[{'symbol': p.get('contract_symbol') or str(key), 'qty': p['qty']}
                                   for key, p in opened.items()], orders=[], symbol=item['contract_symbol'],
                        requested_quantity=qty,
                        limit_price=risk.slippage_adjusted_entry(float(ask)) if corrected else float(ask),
                        max_positions=int(settings.get('max_concurrent_positions', 2)),
                        commission_per_contract=float(fee))
                if reason:
                    decisions.append({'id': tid, 'action': 'skip', 'reason': reason})
                else:
                    debit = (ask * 100 + fee) * qty
                    cash -= debit
                    opened[tid] = {'qty': qty, 'debit': debit, 'ask': ask, 'ticker': ticker,
                                   'mark': max(D(0), D(item.get('entry_bid', item['entry_price'])) - friction),
                                   'marked_at': now, 'contract_symbol': item.get('contract_symbol')}
                    decisions.append({'id': tid, 'action': 'enter', 'quantity': qty, 'debit': float(debit)})
            current = equity()
            peak = max(peak, current)
            drawdown = max(drawdown, peak - current)
            max_open = max(max_open, len(opened))
            max_locked = max(max_locked, sum((p['debit'] for p in opened.values()), D(0)))
            if cash < 0:
                raise AssertionError('Buying power went negative')
        if day:
            daily[str(day)] = float(equity() - day_open)
    wins = sum((D(x['pnl']) for x in closed if x['pnl'] > 0), D(0))
    losses = -sum((D(x['pnl']) for x in closed if x['pnl'] < 0), D(0))
    streak = worst_streak = 0
    for x in closed:
        streak = streak + 1 if x['pnl'] < 0 else 0
        worst_streak = max(streak, worst_streak)
    return {'initial': initial, 'ending_equity': float(equity()), 'settled_cash': float(cash),
            'unsettled_receipts': float(sum((a for _, a in pending), D(0))),
            'receipts_without_future_settlement_session': float(sum((a for dt, a in pending if dt == date.max), D(0))),
            'net_pnl': float(equity() - D(initial)), 'pf': float(wins / losses) if losses else None,
            'closed': closed, 'decisions': decisions, 'max_open': max_open,
            'peak_committed_debit': float(max_locked), 'sampled_drawdown': float(drawdown),
            'daily_pnl': daily, 'longest_losing_streak': worst_streak,
            'stale_mark_uses_at_entry': stale_marks, 'unresolved_emergency_exits': sorted(unresolved_halts),
            'performance_valid_without_emergency_repricing': not unresolved_halts,
            'open_at_end': len(opened), 'corrected_sizing': corrected,
            'ticker_routing': ticker_routing, 'routing_paper': routing_paper,
            'win_cooldown_minutes': 10 if ticker_routing else None,
            'settlement_model': 'next_supplied_session' if sessions is not None else 'weekdays_only',
            'settled_only': settled_only, 'fee_per_side': fee_per_side, 'friction_per_side': friction_per_side}
