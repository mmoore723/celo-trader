"""Explicit pair selections, frozen into new positions. No implicit activation."""
from hashlib import sha256
import json

MINUTES = (30, 60, 90, 120)
CONTRACTS = ('closest_otm_150_1000', 'nearest_weekly_150_1000', 'tightest_spread_150_1000',
             'lowest_ask_150_1000', 'highest_open_interest_150_1000', 'highest_volume_150_1000', 'target_150_250')


def build(sid, ticker, version, minutes=None, contract=None):
    from config.research_order_specs import SPECS
    if sid not in SPECS or SPECS[sid].version != version:
        raise ValueError('Selected test settings require a matching research order route.')
    if SPECS[sid].allowed_tickers and ticker not in SPECS[sid].allowed_tickers:
        raise ValueError('Ticker does not match the selected execution route.')
    if minutes is not None and (type(minutes) is not int or minutes not in MINUTES):
        raise ValueError('Choose a supported exit test: 30, 60, 90 or 120 minutes.')
    if contract is not None and contract not in CONTRACTS:
        raise ValueError('Unsupported contract-selection test.')
    policy = dict(schema=1, strategy_id=sid, ticker=ticker, strategy_version=version,
                  exit_minutes=minutes, contract_policy=contract)
    policy['policy_version'] = 'selected-tests-v1-' + sha256(json.dumps(policy, sort_keys=True).encode()).hexdigest()[:16]
    return policy


def validate(policy, sid, ticker, version):
    if not isinstance(policy, dict):
        raise ValueError('Invalid selected-test policy.')
    expected = build(sid, ticker, version, policy.get('exit_minutes'), policy.get('contract_policy'))
    if policy != expected:
        raise ValueError('Selected-test policy does not match the entry scope or version.')
    return expected


def selected(settings, sid, ticker, version):
    grant = (settings.get('admin_strategy_overrides') or {}).get(f'{sid}:{ticker}') or {}
    policy = grant.get('selected_test_policy')
    if not policy or not grant.get('enabled') or grant.get('strategy_version') != version:
        return None
    if grant.get('approved_by_admin') is not True:
        raise ValueError('Selected-test policy lacks admin approval.')
    return validate(policy, sid, ticker, version)
