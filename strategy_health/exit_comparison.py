"""Paired outcomes only: a missing counterpart can never prove an improvement."""
from collections import Counter
from statistics import median

from strategy_health.momentum_exit import PROTOCOL
from strategy_health.exit_protocols import SHORT_TRAIL_PROTOCOLS
from strategy_health.impulse_exit import et


def totals(rows):
    from strategy_health.authored_exit_summary import net_profit
    profits = [net_profit(r) for r in rows]
    gains, losses = sum(p for p in profits if p > 0), -sum(p for p in profits if p < 0)
    batches = Counter()
    for row, profit in zip(rows, profits):
        batches[row['decision_at']] += profit
    peak = running = drawdown = 0
    for _, profit in sorted(batches.items()):
        running += profit
        peak = max(peak, running)
        drawdown = max(drawdown, peak-running)
    return dict(profit_factor=round(gains/losses, 2) if losses else ('infinite' if gains else None),
                net_pnl=round(sum(profits), 2) if profits else None,
                maximum_drawdown=round(drawdown, 2) if profits else None)


def low_water_comparison(selected, protocol=PROTOCOL):
    from strategy_health.authored_exit_summary import net_profit
    enrolled, original, variant, differences, days = [], [], [], [], set()
    variant_protocol = SHORT_TRAIL_PROTOCOLS[protocol][1]
    for base in selected:
        test = base.get('low_water_variant')
        if not test or base['protocol'] != protocol or test['protocol'] != variant_protocol:
            continue
        enrolled.append(test)
        if any(base[k] != test[k] for k in ('candidate_id', 'contract_symbol', 'entry_ask', 'entry_quote_at')):
            continue
        a, b = net_profit(base), net_profit(test)
        if a is None or b is None:
            continue
        original.append(base)
        variant.append(test)
        differences.append(round(b-a, 2))
        days.add(et(base['entry_quote_at']).date().isoformat())
    return dict(protocol=variant_protocol, tracked=len(enrolled), paired_results=len(original),
                paired_days=len(days), unpaired=len(enrolled)-len(original),
                original=totals(original), corrected=totals(variant),
                average_improvement=round(sum(differences)/len(differences), 2) if differences else None,
                median_improvement=round(median(differences), 2) if differences else None,
                statuses=dict(Counter(r['status'] for r in enrolled)))
