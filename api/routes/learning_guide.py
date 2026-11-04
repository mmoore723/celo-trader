"""Read-only learning references for exact configured strategy pairs."""
from fastapi import HTTPException
from config.strategy_catalog import REVIEWED_STRATEGIES

VWAP = 'CTX_VWAP_PULLBACK_1030_DISPLACEMENT_LONG'


def guide(strategy_id, ticker, version):
    from config import get_settings
    from config.research_order_specs import SPECS
    from config.research_pair_policy import selected
    from scanner.strategy_premarket import _ENTRY
    from strategy_health.exit_measurement import _AUTHORED_EXITS
    rule = REVIEWED_STRATEGIES.get(strategy_id)
    if not rule or rule.version != version:
        raise HTTPException(404, 'This strategy version has no current learning reference.')
    source = SPECS[strategy_id].source if strategy_id in SPECS else strategy_id
    steps = [_ENTRY[source]] if source in _ENTRY else []
    if source == 'V2_FAILED_OR_BREAK_VWAP_REVERSION':
        steps = ['Build the 9:30 to 9:44 AM Eastern opening range. Require a completed breakout by 11 AM, then an opposite-color close back inside by noon.',
                 'The breakout must extend at least 5% of the range width. At the failure, require at least 5% of that width in room toward VWAP. The failed break sets the opposite trade direction.']
    if source == VWAP:
        steps = [
            'At 10:30 AM Eastern, the completed 10:25 to 10:30 candle must close at least 1% above session VWAP.',
            'Then wait for a completed five-minute pullback candle starting at or after 10:30. The previous candle must have closed above VWAP.',
            'The pullback low must touch or cross VWAP, and its close must finish above EMA 9. The earlier session high must still be above the close.',
            'This is a bullish setup. A qualifying chart signal still needs an eligible option quote and passing account safety checks.',
        ]
    policy = selected(get_settings(), strategy_id, ticker.upper(), version)
    exit_copy = _AUTHORED_EXITS.get(source, 'Consult the native strategy exit reference in Research.')
    if policy and policy.get('exit_minutes') is not None:
        exit_copy = f"This pair uses your selected {policy['exit_minutes']}-minute exit for new entries, with mandatory safety and session exits still active."
    return dict(strategy_id=strategy_id, ticker=ticker.upper(), version=version,
                name=rule.display_name, steps=steps, exit=exit_copy,
                evidence=rule.evidence, policy_version=policy.get('policy_version') if policy else 'Native strategy policy',
                selected_policy=bool(policy and policy.get('exit_minutes') is not None),
                source=source, order_authority=False)
