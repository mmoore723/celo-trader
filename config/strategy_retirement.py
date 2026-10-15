def identity(strategy_id, version):
    from config.research_order_specs import SPECS
    spec = SPECS.get(strategy_id)
    source = spec.source if spec and spec.version == version else strategy_id
    return f'{source}:{version}'


def is_retired(settings, strategy_id, version):
    return identity(strategy_id, version) in (settings.get('retired_strategy_versions') or [])


def active_ids(settings, strategy_ids):
    from config.strategy_catalog import REVIEWED_STRATEGIES
    return {sid for sid in strategy_ids
            if sid not in REVIEWED_STRATEGIES or not is_retired(settings, sid, REVIEWED_STRATEGIES[sid].version)}


def inventory(settings):
    from config.strategy_catalog import REVIEWED_STRATEGIES
    from trading.tested_strategy_research import TESTED_RESEARCH_STRATEGIES
    rows = {}
    for rule in (*REVIEWED_STRATEGIES.values(), *TESTED_RESEARCH_STRATEGIES.values()):
        key = identity(rule.strategy_id, rule.version)
        rows.setdefault(key, {'strategy_id': rule.strategy_id, 'version': rule.version,
                              'display_name': rule.display_name,
                              'removed': is_retired(settings, rule.strategy_id, rule.version)})
    return sorted(rows.values(), key=lambda row: (row['display_name'], row['version']))


def updates(settings, strategy_id, version, removed):
    key = identity(strategy_id, version)
    if not any(identity(row['strategy_id'], row['version']) == key for row in inventory(settings)):
        raise ValueError('Unknown strategy version')
    retired = set(settings.get('retired_strategy_versions') or [])
    if removed:
        retired.add(key)
    else:
        retired.discard(key)
    return {'retired_strategy_versions': sorted(retired)}
