"""Pure paired shadow pricing. No strategy decisions, enrollment or order access.

Native/candidate adapters must supply independently verified intents. This module
does not certify their rules or reconstruct decisions from later market data.
"""
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from collections import defaultdict
from zoneinfo import ZoneInfo


def clock(value):
    if not isinstance(value,datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError('aware_timestamp_required')
    return value


def money(value):
    try: result=Decimal(str(value))
    except (InvalidOperation,ValueError): raise ValueError('invalid_money') from None
    if not result.is_finite(): raise ValueError('invalid_money')
    return result


def quantity(value):
    if isinstance(value,bool) or not isinstance(value,int) or value<1:
        raise ValueError('positive_integer_quantity_required')
    return value


@dataclass(frozen=True)
class Scope:
    account: str
    mode: str
    strategy: str
    ticker: str
    version: str
    experiment: str

    def validate(self):
        if self.mode not in ('paper','live') or any(not isinstance(x,str) or not x.strip()
                for x in (self.account,self.strategy,self.ticker,self.version,self.experiment)):
            raise ValueError('complete_bucket_scope_required')


@dataclass(frozen=True)
class Entry:
    scope: Scope
    trade_id: str
    contract: str
    filled_at: datetime
    premium: Decimal
    contracts: int
    entry_fees: Decimal
    fill_evidence_id: str


@dataclass(frozen=True)
class Intent:
    at: datetime
    contracts: int
    reason: str
    evidence_id: str


@dataclass(frozen=True)
class Quote:
    contract: str
    received_at: datetime
    bid_at: datetime
    ask_at: datetime
    bid: Decimal
    ask: Decimal
    bid_size: int
    evidence_id: str


@dataclass(frozen=True)
class Pricing:
    max_wait_seconds: float
    max_source_age_seconds: float
    max_receipt_gap_seconds: float
    slippage_per_share: Decimal
    exit_fee_per_contract: Decimal
    fee_schedule_version: str

    def validate(self):
        for x in (self.max_wait_seconds,self.max_source_age_seconds,self.max_receipt_gap_seconds):
            if not 0 < float(x) < float('inf'): raise ValueError('positive_finite_timing_required')
        if money(self.slippage_per_share)<0 or money(self.exit_fee_per_contract)<0 or not self.fee_schedule_version:
            raise ValueError('explicit_nonnegative_cost_schedule_required')


def _usable(q, config):
    try:
        bid, ask = money(q.bid), money(q.ask)
        ages = [(q.received_at-t).total_seconds() for t in (q.bid_at,q.ask_at)]
        return (0 < bid <= ask and all(0 <= a <= config.max_source_age_seconds for a in ages)
                and not isinstance(q.bid_size,bool) and isinstance(q.bid_size,int) and q.bid_size > 0)
    except (ValueError,TypeError):
        return False


def _price(entry, intents, quotes, config):
    """First valid observed bid after each intent. No stale carry-forward fills."""
    fills=[]; used=set(); left=entry.contracts; prior=entry.filled_at
    if not intents: raise ValueError('missing_exit_intents')
    for intent in intents:
        clock(intent.at); quantity(intent.contracts)
        if intent.at<prior or not intent.reason or not intent.evidence_id:
            raise ValueError('invalid_or_unproven_exit_intent')
        if intent.contracts>left: raise ValueError('exit_quantity_exceeds_position')
        selected=None
        for q in quotes:
            if q.received_at<intent.at or q.received_at<prior: continue
            if (q.received_at-intent.at).total_seconds()>config.max_wait_seconds: break
            if q.evidence_id in used: continue
            if not _usable(q,config) or q.bid_size<intent.contracts: continue
            selected=q;break
        if selected is None: raise ValueError('unavailable_eligible_exit_quote')
        used.add(selected.evidence_id)
        price=max(Decimal(0),money(selected.bid)-money(config.slippage_per_share))
        fills.append({'at':selected.received_at,'quantity':intent.contracts,'premium':price,
                      'fee':money(config.exit_fee_per_contract)*intent.contracts,
                      'reason':intent.reason,'intent_evidence':intent.evidence_id,'quote_evidence':selected.evidence_id})
        prior=selected.received_at;left-=intent.contracts
    if left: raise ValueError('incomplete_exit_quantity')
    net=sum((f['premium']*100*f['quantity']-f['fee'] for f in fills),Decimal(0))
    net-=money(entry.premium)*100*entry.contracts+money(entry.entry_fees)
    return {'net':net,'closed_at':fills[-1]['at'],'fills':fills}


def compare(entry, baseline, candidate, quotes, pricing, *, baseline_policy, candidate_policy):
    """One paired attempt. Explicit failures are retained, never priced as zero."""
    result={'scope':entry.scope,'trade_id':entry.trade_id,'contract':entry.contract,
            'status':'blocked','result_kind':'hypothetical shadow','errors':[],
            'baseline_policy':baseline_policy,'candidate_policy':candidate_policy,
            'entry_at':entry.filled_at,'entry_fill_evidence':entry.fill_evidence_id,
            'fee_schedule_version':pricing.fee_schedule_version}
    try:
        entry.scope.validate();pricing.validate();clock(entry.filled_at);quantity(entry.contracts)
        if (not entry.trade_id or not entry.contract or not entry.fill_evidence_id
                or not baseline_policy or not candidate_policy
                or money(entry.premium)<=0 or money(entry.entry_fees)<0):
            raise ValueError('incomplete_entry_or_policy_evidence')
        seen={}; normalized=[]
        for q in quotes:
            if q.contract!=entry.contract: raise ValueError('quote_contract_mismatch')
            for t in (q.received_at,q.bid_at,q.ask_at): clock(t)
            if not q.evidence_id: raise ValueError('missing_quote_evidence')
            if q.evidence_id in seen:
                if seen[q.evidence_id]!=q: raise ValueError('conflicting_duplicate_quote')
                continue
            seen[q.evidence_id]=q;normalized.append(q)
        normalized.sort(key=lambda q:(q.received_at,q.evidence_id))
        for name,intents in (('baseline',baseline),('candidate',candidate)):
            try: result[name]=_price(entry,intents,normalized,pricing)
            except (ValueError,TypeError) as exc: result['errors'].append(name+':'+str(exc))
        if result['errors']: return result
        end=max(result['baseline']['closed_at'],result['candidate']['closed_at'])
        receipts=[entry.filled_at]+[q.received_at for q in normalized
            if entry.filled_at<=q.received_at<=end and _usable(q,pricing)]+[end]
        if any((b-a).total_seconds()>pricing.max_receipt_gap_seconds for a,b in zip(receipts,receipts[1:])):
            raise ValueError('quote_receipt_gap_through_later_exit')
        result.update(status='evaluable',improvement=result['candidate']['net']-result['baseline']['net'],
            baseline_winner_to_loss=result['baseline']['net']>0 and result['candidate']['net']<0,
            session=entry.filled_at.astimezone(ZoneInfo('America/New_York')).date().isoformat())
    except (ValueError,TypeError) as exc:
        result['errors'].append(str(exc))
    return result


def _metrics(rows,branch):
    amounts=[r[branch]['net'] for r in rows]
    if not amounts: return {'trades':0,'net':None,'win_rate':None,'profit_factor':None,'worst_loss':None,'closed_trade_drawdown':None}
    gains=sum((p for p in amounts if p>0),Decimal(0));losses=-sum((p for p in amounts if p<0),Decimal(0))
    realized=defaultdict(Decimal)
    for r in rows: realized[r[branch]['closed_at']]+=r[branch]['net']
    peak=running=drawdown=Decimal(0)
    for _,amount in sorted(realized.items()):
        running+=amount;peak=max(peak,running);drawdown=max(drawdown,peak-running)
    return {'trades':len(rows),'net':sum(amounts,Decimal(0)),
        'win_rate':sum(p>0 for p in amounts)/len(amounts),
        'profit_factor':gains/losses if losses else ('infinite' if gains else None),
        'worst_loss':min(Decimal(0),min(amounts)),'closed_trade_drawdown':drawdown}


def summarize(attempts):
    """Separate every scope and policy pair. No overall pooled winner."""
    groups=defaultdict(list);seen=set()
    for r in attempts:
        key=(r['scope'],r['baseline_policy'],r['candidate_policy'])
        identity=(key,r['trade_id'])
        if identity in seen: raise ValueError('duplicate_paired_attempt')
        seen.add(identity);groups[key].append(r)
    output=[]
    for key,rows in groups.items():
        valid=[r for r in rows if r['status']=='evaluable']
        output.append({'scope':key[0],'baseline_policy':key[1],'candidate_policy':key[2],
            'attempts':len(rows),'evaluable':len(valid),'blocked':len(rows)-len(valid),
            'sessions':len({r['session'] for r in valid}),
            'baseline':_metrics(valid,'baseline'),'candidate':_metrics(valid,'candidate'),
            'paired_mean_improvement':sum((r['improvement'] for r in valid),Decimal(0))/len(valid) if valid else None,
            'baseline_winners_turned_losses':sum(r['baseline_winner_to_loss'] for r in valid),
            'uncertainty':None,'recommendation':'INSUFFICIENT EVIDENCE',
            'qualification':'not implemented here; frozen criteria, causal input validation and holdout required'})
    return output
