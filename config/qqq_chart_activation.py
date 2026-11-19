"""Explicitly invoked admin approval migration. Never runs on startup."""
from copy import deepcopy
from datetime import datetime, timezone
from trading.premium_policy import scope, fingerprint, freeze_selection
from trading.chart_invalidation_exit import SPEC, PAIR
from config.engine_parameters import KEY, scope_key, revision

def approved_updates(settings):
    if settings.get('paper_trading') is not True:
        raise ValueError('QQQ approval is for the current paper account only')
    account=settings.get('active_broker_account_id')
    sid,ticker=PAIR
    version='2.1.0'
    key=scope(account,sid,ticker,version)
    frozen=freeze_selection(settings,sid,ticker,version).get('premium_exit_policy')
    if not frozen or not frozen.get('replace_native_exit') or (frozen.get('gain_pct'),frozen.get('giveback_pct'),frozen.get('partial_sell_pct',50))!=(10,10,50):
        raise ValueError('QQQ current profit settings differ from the approved 10/10 policy')
    assignments=deepcopy(settings['premium_exit_paper_assignments'])
    policy=assignments[key]
    policy.update(adverse_candle_failsafe=None,chart_invalidation_exit=dict(SPEC),
        approval_id='user-approved-qqq-chart-5m-20261119',approved_at=datetime.now(timezone.utc).isoformat(),
        evidence_status='EXPLORATORY_INCOMPLETE_USER_APPROVED')
    policy['fingerprint']=fingerprint(policy)
    updates={'premium_exit_paper_assignments':assignments}
    configs=deepcopy(settings.get(KEY) or {})
    ck=scope_key(settings,sid,ticker,version)
    if configs.get(ck,{}).get('profit') is not None:
        item=configs[ck]
        item['profit'].update(adverse_candle_failsafe=None,chart_invalidation_exit=dict(SPEC))
        item['base_policy_fingerprint']=policy['fingerprint']
        item['revision']=revision({k:v for k,v in item.items() if k!='revision'})
        updates[KEY]=configs
    verified=freeze_selection({**settings,**updates},sid,ticker,version)['premium_exit_policy']
    assert verified['chart_invalidation_exit']==SPEC and verified.get('adverse_candle_failsafe') is None
    return updates
