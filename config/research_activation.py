"""Read-only activation preflight. Capability never grants trading permission."""
from config.research_order_specs import SPECS, execution_id


def capability(settings, source, ticker, version):
    from config.strategy_catalog import REVIEWED_STRATEGIES, reviewed_strategy_integrity_errors, reviewed_exit_summary
    from config.admin_strategy_overrides import allowed_ticker, active
    from strategy_health.closed_trade_guard import is_paused
    from config.strategy_retirement import is_retired
    symbol = ticker.strip().upper()
    sid = execution_id(source.strip().upper(), version, symbol)
    rule = REVIEWED_STRATEGIES.get(sid)
    reason = None
    if rule is None or rule.version != version or rule.observation_only:
        reason = 'This saved research version is not connected to execution. No settings will be saved.'
    elif is_retired(settings, sid, version):
        reason = 'This strategy version is retired. Restore it before approving a ticker.'
    elif sid in reviewed_strategy_integrity_errors():
        reason = 'The execution release could not be verified. No settings will be saved.'
    elif not allowed_ticker(sid, symbol, rule):
        reason = 'This ticker is not supported by this exact rule.'
    elif is_paused(settings, sid, symbol, version):
        reason = 'This pair is paused by its closed-trade loss control. Turning it on cannot override that protection.'
    spec = SPECS.get(sid)
    return dict(ready=reason is None, reason=reason, strategy_id=sid,
                source_strategy_id=spec.source if spec else source, ticker=symbol, strategy_version=version,
                configurable_tests=spec is not None, approved=active(settings, sid, symbol),
                baseline_exit=reviewed_exit_summary(sid) if rule else None,
                paper_mode=bool(settings.get('paper_trading', True)),
                explanation='Approval saves this ticker under the shared strategy. Orders still require a setup and passing account safety checks.')
