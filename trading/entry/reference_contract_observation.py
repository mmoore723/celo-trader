"""Prospective reviewed-contract cohort. Quotes and telemetry only; no orders."""
from dataclasses import asdict
from datetime import timedelta
import logging

from config.strategy_catalog import REVIEWED_STRATEGIES
from database.reference_contract_tests import PROFILE, STRATEGIES, record
from strategy_health.impulse_exit import et, executable_bid
from trading.entry.contract import reviewed_contract_profile, select_reviewed_v2_contract
from trading.research_contract_selection import RESEARCH_MAX_CONTRACT_DOLLARS
from trading.state import _now_et

logger = logging.getLogger('celo_trader.research')


def observe(*, candidate_id, strategy_id, ticker, direction, price, meta, tradier,
            selection_cache=None, clock=_now_et):
    """Keep one separate entry, even when the generic research option is absent.

    Share a five-second selection/quote snapshot across identical profiles in
    one ticker pass. The research ceiling is $1,000 per contract, NOT an
    account's buying power or a claim that its order would have filled.
    """
    if strategy_id not in STRATEGIES:
        return
    rule = REVIEWED_STRATEGIES[strategy_id]
    if str(meta.get('strategy_version') or '') != rule.version:
        return
    profile = reviewed_contract_profile(strategy_id, ticker)
    key = (PROFILE, profile, ticker.upper(), direction, round(price, 4))
    now = et(clock())
    cached = selection_cache.get(key) if selection_cache is not None else None
    cache_fresh = cached and 0 <= (now-et(cached[1]['received_at'])).total_seconds() <= 5
    if cache_fresh and cached[0]:
        cache_fresh = all(0 <= (now-et(cached[1][key])).total_seconds() <= 60
                          for key in ('bid_at', 'ask_at'))
    if cache_fresh:
        contract, info = cached
    else:
        contract, info = None, {'reason': 'api_error'}
        try:
            chosen, selected = select_reviewed_v2_contract(
                tradier, ticker, direction, price, RESEARCH_MAX_CONTRACT_DOLLARS,
                for_display=True, strategy_id=strategy_id,
            )
            info = {'reason': selected.get('reason', 'not_selected')}
            if chosen:
                # Chains are eligibility snapshots, not timestamped entry fills.
                quote = tradier.get_option_quote(chosen['symbol'])
                received = et(clock())
                args = dict(contract=chosen['symbol'], decision_at=received-timedelta(seconds=60), received_at=received)
                bid = executable_bid(quote, **args)
                ask = executable_bid(dict(quote or {}, bid_date=(quote or {}).get('ask_date')), **args)
                if bid and ask:
                    premium = float(quote['ask'])
                    spread = (premium-bid[0])/((premium+bid[0])/2)
                    if (profile.minimum_premium <= premium <= profile.maximum_premium
                            and spread <= profile.maximum_spread_pct):
                        contract = dict(chosen, **{k: quote[k] for k in ('bid', 'ask')})
                        info.update(reason='selected', bid_at=bid[1], ask_at=ask[1])
                    else:
                        info['reason'] = 'fresh_quote_outside_profile'
                else:
                    info['reason'] = 'entry_quote_unavailable'
        except Exception:
            info['reason'] = 'api_error'
            logger.warning('Reference contract read unavailable for %s; no result invented', ticker)
        info['received_at'] = et(clock()).isoformat()
        if selection_cache is not None:
            selection_cache[key] = (contract, info)
    # Each play starts when it is observed, never before its trigger because
    # another strategy happened to cache a quote a few seconds earlier.
    observed = et(clock())
    if contract and not all(0 <= (observed-et(info[key])).total_seconds() <= 60 for key in ('bid_at','ask_at')):
        contract, info = None, dict(info, reason='entry_quote_unavailable')
    record(candidate_id=candidate_id, strategy_id=strategy_id, direction=direction,
           meta=meta, contract=contract, observed_at=observed,
           details=dict(info, rules=asdict(profile), research_cap_dollars=RESEARCH_MAX_CONTRACT_DOLLARS))
