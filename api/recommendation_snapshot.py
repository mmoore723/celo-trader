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
    compact = {'strategies': [{
        'strategy_id': strategy['strategy_id'], 'version': strategy['version'],
        'display_name': strategy['display_name'],
        'pairs': [{key: deepcopy(pair[key]) for key in
                   ('ticker', 'tradable', 'research_contract_profile', 'recommendation') if key in pair}
                  for pair in strategy['pairs'] if pair.get('recommendation')],
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
