"""Verify saved Displacement arithmetic and current sizing, not fillability."""
import argparse
from dataclasses import asdict
from decimal import Decimal as D
import hashlib
import json
import os
from pathlib import Path

from auth.context import set_current_user
from config.research_snapshot import research_settings_snapshot
from risk.manager import RiskManager
from trading.entry.contract import reviewed_contract_profile

SID = 'CTX_VWAP_PULLBACK_1030_DISPLACEMENT_LONG'


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def audit(report, settings):
    if report['protocol'] != 'displacement_recovered_complete_cohort_assessment_v1':
        raise ValueError('Unexpected source protocol')
    rows = [r for r in report['rows'] if r['profile'] == 'reviewed_bounds' and r['native'] and r['independent']]
    if len(rows) != 7 or len({r['candidate_id'] for r in rows}) != 7:
        raise ValueError('Native seven-setup cohort changed')
    result = []
    set_current_user('account-replay', 'account-replay', False)
    with research_settings_snapshot('account-replay', settings):
        risk = RiskManager(5000)
        profile = reviewed_contract_profile(SID, 'TSLA')
        for row in rows:
            legs = {}
            for name in ('structural', 'timer'):
                leg = row['legs'][name]
                if leg['status'] != 'priced':
                    raise ValueError('Incomplete native leg')
                net = (D(leg['exit_bid']) - D(row['entry_ask'])) * 100 - D('3.30')
                if net != D(str(leg['net_pnl_one_contract'])):
                    raise ValueError('Saved price arithmetic differs')
                legs[name] = str(net)
            result.append(dict(id=row['candidate_id'], ticker=row['ticker'],
                               entry=row['entry_snapshot_at'], ask=row['entry_ask'],
                               net_one_contract=legs,
                               contracts_at_5000=risk.calculate_contracts(
                                   risk.slippage_adjusted_entry(float(row['entry_ask'])), 5000, strategy_id=SID)))
        budgets = []
        for balance in (5000, 4999):
            budgets.append(dict(balance=balance, risk_fraction=risk.effective_risk_pct(balance),
                                risk_dollars=balance*risk.effective_risk_pct(balance),
                                maximum_ask=risk.max_affordable_premium(balance, strategy_id=SID)))
        return dict(profile=asdict(profile), rows=result, budget_boundary=budgets,
                    eligible_profile_minimum_fits_5000=profile.minimum_premium <= budgets[0]['maximum_ask'],
                    minimum_profile_quantity_at_5000=risk.calculate_contracts(
                        risk.slippage_adjusted_entry(profile.minimum_premium), 5000, strategy_id=SID),
                    full_account_performance_proven=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('assessment', 'settings', 'output'):
        parser.add_argument('--'+name, type=Path, required=True)
    args = parser.parse_args()
    report = json.loads(args.assessment.read_text())
    for path, expected in report['input_hashes'].items():
        if digest(path) != expected:
            raise ValueError('Source input hash changed')
    verified = json.loads(args.settings.read_text())
    if verified.get('all_checks_pass') is not True:
        raise ValueError('Settings source not verified')
    result = dict(protocol='displacement_native_account_fit_v1',
                  sources={str(p): digest(p) for p in (args.assessment, args.settings, Path(__file__),
                      Path('risk/sizing.py'), Path('trading/entry/contract.py'))},
                  audit=audit(report, verified['risk_settings']),
                  limitations=['Uses saved price arithmetic and verified source hashes; not a new raw chain audit',
                    'Seven historical setups are not enough to establish future profitability',
                    'No intratrade quote paths, simultaneous portfolio or market fills verified here',
                    'No settings, selection policy or trading behavior changed'])
    fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as output:
        json.dump(result, output, indent=2, allow_nan=False)
    print(json.dumps(result['audit'], indent=2))


if __name__ == '__main__':
    main()
