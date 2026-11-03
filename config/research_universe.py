"""User-scoped research selection. Never grants execution permission."""
import re

SETTING = 'research_tickers'


def selected_tickers(settings):
    """None preserves legacy discovery; an explicit empty list enrolls nothing."""
    if SETTING not in settings:
        return None
    values = settings[SETTING]
    if not isinstance(values, list):
        raise ValueError('research_tickers must be a list')
    result = []
    for value in values:
        if not isinstance(value, str) or not re.fullmatch(r'[A-Z][A-Z0-9.-]{0,11}', value.strip().upper()):
            raise ValueError('Invalid research ticker')
        ticker = value.strip().upper()
        if ticker not in result:
            result.append(ticker)
    return result


def collection_tickers(settings, fallback):
    selected = selected_tickers(settings)
    return list(fallback) if selected is None else selected


def filter_research_display(matrix, settings):
    """Filter before pagination/analytics without changing saved evidence."""
    selected = selected_tickers(settings)
    if selected is None:
        return matrix
    allowed = set(selected)
    strategies = [{**row, 'pairs': [pair for pair in row['pairs'] if pair['ticker'] in allowed]}
                  for row in matrix['strategies']]
    return {**matrix, 'strategies': strategies,
            'ticker_count': len({pair['ticker'] for row in strategies for pair in row['pairs']}),
            'research_universe': selected, 'research_scope': 'focused',
            'scanner_source': 'Configured research universe',
            'scanner_source_size': 0, 'scanner_shortlist_size': 0}
