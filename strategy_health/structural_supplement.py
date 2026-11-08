"""Causal structural supplement for research only. No policy enrollment/orders.

Adapters must supply verified entry evidence and baseline shadow fills. This
module does not infer levels, replace native rules, or certify decision coverage.
"""
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from strategy_health.paired_exit_accounting import Scope, Intent, clock, money, quantity, compare


@dataclass(frozen=True)
class StockPrint:
    ticker: str
    price: Decimal
    source_at: datetime
    received_at: datetime
    source_event_id: str
    evidence_id: str
    source: str
    provenance: str


@dataclass(frozen=True)
class EntryLevel:
    scope: Scope
    trade_id: str
    field: str
    value: Decimal
    source_completed_at: datetime
    recorded_at: datetime
    evidence_id: str


@dataclass(frozen=True)
class StructuralSpec:
    level_field: str
    option_type: str
    source: str
    max_source_age_seconds: float
    max_receipt_gap_seconds: float
    specification_hash: str

    def validate(self):
        if (self.option_type not in ('call','put') or not self.level_field
                or not self.source or not self.specification_hash):
            raise ValueError('incomplete_structural_specification')
        for value in (self.max_source_age_seconds,self.max_receipt_gap_seconds):
            if not 0 < float(value) < float('inf'): raise ValueError('invalid_freshness_specification')


def level_from_context(entry, metadata, field, *, source_completed_at, recorded_at, evidence_id):
    """Select only the named field. Never fall back to another stop or level."""
    value=metadata
    for key in field.split('.'):
        if not isinstance(value,dict) or key not in value: raise ValueError('missing_entry_level:'+field)
        value=value[key]
    return EntryLevel(entry.scope,entry.trade_id,field,money(value),source_completed_at,recorded_at,evidence_id)


def _print_problem(p, spec, ticker):
    if p.ticker!=ticker: return 'wrong_ticker'
    if p.source!=spec.source: return 'wrong_source'
    if p.provenance!='forward_observed': return 'not_forward_observed'
    if not p.source_event_id or not p.evidence_id: return 'missing_price_evidence'
    try:
        clock(p.source_at);clock(p.received_at)
        if money(p.price)<=0: return 'invalid_price'
        age=(p.received_at-p.source_at).total_seconds()
        if not 0<=age<=spec.max_source_age_seconds: return 'stale_or_future_source'
    except (ValueError,TypeError): return 'invalid_price_or_clock'
    return None


def candidate_intents(entry, native_intents, native_fills, level, entry_stock, prints, spec):
    """Compose one structural hypothesis with unchanged native action intents.

    Full native requests already triggered always retain precedence. Completed
    partials retain their size. An unresolved partial at breach is not simulated
    as if cancellation or fills were known. Returns blocked with exact cause.
    """
    result={'status':'blocked','errors':[],'rejected_prints':{},'intents':None,
            'specification_hash':spec.specification_hash,'decision_coverage_verified':False,
            'result_kind':'hypothetical structural supplement'}
    try:
        entry.scope.validate();clock(entry.filled_at);quantity(entry.contracts);spec.validate()
        if level is None: raise ValueError('missing_entry_level')
        if level.scope!=entry.scope or str(level.trade_id)!=str(entry.trade_id): raise ValueError('level_scope_mismatch')
        if level.field!=spec.level_field or not level.evidence_id: raise ValueError('wrong_or_unproven_level_field')
        clock(level.source_completed_at);clock(level.recorded_at)
        if not level.source_completed_at<=level.recorded_at<=entry.filled_at:
            raise ValueError('level_not_available_at_entry')
        boundary=money(level.value)
        if boundary<=0: raise ValueError('invalid_entry_level')
        problem=_print_problem(entry_stock,spec,entry.scope.ticker)
        if problem: raise ValueError('entry_stock:'+problem)
        if entry_stock.received_at>entry.filled_at or (entry.filled_at-entry_stock.source_at).total_seconds()>spec.max_source_age_seconds:
            raise ValueError('entry_stock_not_current_at_entry')
        if not (boundary<money(entry_stock.price) if spec.option_type=='call' else boundary>money(entry_stock.price)):
            raise ValueError('entry_level_wrong_side')
        if not native_intents or len(native_intents)!=len(native_fills): raise ValueError('missing_native_fill_mapping')
        left=entry.contracts;prior=entry.filled_at
        for intent,fill in zip(native_intents,native_fills):
            clock(intent.at);clock(fill['at']);quantity(intent.contracts);quantity(fill['quantity'])
            if (not prior<=intent.at<=fill['at'] or intent.contracts>left
                    or not intent.evidence_id or not intent.reason
                    or fill['quantity']!=intent.contracts or fill['intent_evidence']!=intent.evidence_id
                    or fill['reason']!=intent.reason or not fill.get('quote_evidence')):
                raise ValueError('invalid_native_fill_mapping')
            left-=intent.contracts;prior=fill['at']
        if left: raise ValueError('native_position_unfinished')
        end=native_fills[-1]['at']
        # Validate evidence identity before deduplicating source observations.
        evidence={};source_events={};valid=[];rejected=Counter()
        for p in prints:
            problem=_print_problem(p,spec,entry.scope.ticker)
            if problem:
                rejected[problem]+=1;continue
            if p.evidence_id in evidence and evidence[p.evidence_id]!=p:
                raise ValueError('conflicting_stock_evidence')
            evidence[p.evidence_id]=p
            source_identity=(p.source_at,money(p.price))
            if p.source_event_id in source_events and source_events[p.source_event_id]!=source_identity:
                raise ValueError('conflicting_stock_source_event')
            source_events[p.source_event_id]=source_identity
            if entry.filled_at<=p.received_at<=end and p.source_at>=entry.filled_at: valid.append(p)
        result['rejected_prints']=dict(rejected)
        valid.sort(key=lambda p:(p.received_at,p.evidence_id))
        unique=[];seen=set()
        for p in valid:
            if p.source_event_id in seen: continue
            seen.add(p.source_event_id);unique.append(p)
        if not unique: raise ValueError('missing_underlying_prices')
        receipts=[entry.filled_at]+[p.received_at for p in unique]+[end]
        if any((b-a).total_seconds()>spec.max_receipt_gap_seconds for a,b in zip(receipts,receipts[1:])):
            raise ValueError('underlying_gap_through_native_exit')
        breach=next((p for p in unique if (money(p.price)<boundary if spec.option_type=='call' else money(p.price)>boundary)),None)
        result.update(level_evidence=level.evidence_id,level_value=boundary,level_field=level.field,
                      underlying_observations=len(unique),trigger_evidence=breach.evidence_id if breach else None)
        if breach is None:
            result.update(status='ready_for_pricing',intents=list(native_intents),action='native_unchanged_no_observed_breach')
            return result
        left=entry.contracts;kept=[]
        for intent,fill in zip(native_intents,native_fills):
            if intent.at>breach.received_at: break
            if intent.contracts==left:
                result.update(status='ready_for_pricing',intents=list(native_intents),action='native_full_exit_already_triggered')
                return result
            if fill['at']>=breach.received_at:
                raise ValueError('breach_overlaps_native_partial_execution')
            kept.append(intent);left-=intent.contracts
        kept.append(Intent(breach.received_at,left,'structural_adverse_breach',breach.evidence_id))
        result.update(status='ready_for_pricing',intents=kept,action='structural_full_exit',trigger_at=breach.received_at)
    except (ValueError,TypeError,KeyError,AttributeError) as exc:
        result['errors'].append(str(exc))
    return result


def evaluate_pair(entry, native_intents, level, entry_stock, prints, spec, quotes, pricing, *, baseline_policy, candidate_policy):
    """Price native actions first so structural sizing uses the same fill model.

    This explicit offline call does not grant experiment eligibility. Verified
    decision coverage, frozen approvals and archive provenance remain required.
    """
    quotes=list(quotes);native_intents=list(native_intents)
    baseline=compare(entry,native_intents,native_intents,quotes,pricing,
                     baseline_policy=baseline_policy,candidate_policy=candidate_policy)
    if baseline['status']!='evaluable':
        return dict(baseline,input_stage='native_option_pricing',decision_coverage_verified=False)
    structural=candidate_intents(entry,native_intents,baseline['baseline']['fills'],level,entry_stock,prints,spec)
    if structural['status']!='ready_for_pricing':
        return dict(scope=entry.scope,trade_id=entry.trade_id,contract=entry.contract,status='blocked',
                    baseline_policy=baseline_policy,candidate_policy=candidate_policy,
                    errors=structural['errors'],structural=structural,input_stage='structural_inputs',
                    result_kind='hypothetical shadow',decision_coverage_verified=False)
    paired=compare(entry,native_intents,structural['intents'],quotes,pricing,
                   baseline_policy=baseline_policy,candidate_policy=candidate_policy)
    return dict(paired,structural=structural,input_stage='paired_option_pricing',decision_coverage_verified=False)
