from collections import OrderedDict
from copy import deepcopy
from threading import Lock
from time import monotonic

from fastapi import HTTPException


_offers = OrderedDict()
_lock = Lock()
TTL_SECONDS = 300
MAX_SCOPES = 128


def _scope(settings):
    from auth.context import get_current_user_id
    from config import get_db_path
    return (get_current_user_id(), str(get_db_path()),
            bool(settings.get('paper_trading', True)),
            str(settings.get('active_broker_account_id') or ''))


def remember(matrix, settings):
    def compact_pair(pair):
        result={key:deepcopy(pair[key]) for key in
            ('ticker','tradable','research_contract_profile','recommendation','setups',
             'option_results','option_result_days','quote_coverage_pct','mistimed_quotes_ignored',
             'contract_selection_reasons','exit_comparison','contract_tests') if key in pair}
        report=pair.get('premium_exit_research')
        if report:
            report=report.get('execution_validation',report)
            result['premium_exit_research']={**{k:deepcopy(v) for k,v in report.items() if k not in ('candidates','execution_validation')},
                'candidates':[{k:deepcopy(v) for k,v in c.items() if k!='trades'} for c in report['candidates']]}
        return result
    compact = {'strategies': [{
        'strategy_id': strategy['strategy_id'], 'version': strategy['version'],
        'display_name': strategy['display_name'],
        'pairs': [compact_pair(pair) for pair in strategy['pairs'] if pair.get('recommendation') or pair.get('premium_exit_research')],
    } for strategy in matrix['strategies']]}
    scope = _scope(settings)
    with _lock:
        _offers[scope] = (monotonic(), compact)
        _offers.move_to_end(scope)
        while len(_offers) > MAX_SCOPES:
            _offers.popitem(last=False)


def for_decision(settings):
    scope = _scope(settings)
    with _lock:
        entry = _offers.get(scope)
        if entry is not None and monotonic() - entry[0] < TTL_SECONDS:
            return deepcopy(entry[1])
        _offers.pop(scope, None)
    raise HTTPException(409, 'Refresh Settings to load the current recommendation before deciding.')
