"""Teaching copy from saved decision-time evidence only. No trading side effects."""
import math


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def explain_decision(row, context, metadata, reason, detail, source):
    screen = metadata.get('premarket_screen') or {}
    evidence = screen.get('evidence') or {}
    plan = context.get('entry_plan') or {}
    price = plan.get('underlying_price')
    timeframe = metadata.get('timeframe_minutes')
    side = ('a possible call' if row.get('direction') in ('bullish', 'long', 'call')
            else 'a possible put' if row.get('direction') in ('bearish', 'short', 'put')
            else 'a possible trade')
    saw = f"The strategy found {side} setup"
    if number(price):
        saw += f" with the stock at ${price:,.2f}"
    if number(timeframe):
        saw += f" on its {timeframe:g}-minute chart"
    saw += '. A setup is a possible trade, not permission to buy.'
    checks = []
    if reason == 'premarket_screen_rejected':
        for code in screen.get('reasons') or []:
            if code == 'premarket_rvol_below_minimum' and number(evidence.get('rvol')) and number(screen.get('minimum_rvol')):
                checks.append({'name': 'Trading activity before the open',
                    'saw': f"{row.get('ticker')} had {evidence['rvol'] * 100:.1f}% of its usual premarket volume.",
                    'required': f"This strategy required at least {screen['minimum_rvol'] * 100:g}% of usual volume.",
                    'meaning': 'There was not enough premarket activity for this rule, so the bot stopped the setup before ordering. This compares activity before the open, not volume at the afternoon signal.'})
            elif code == 'premarket_gap_below_minimum' and number(evidence.get('gap_pct')) and number(screen.get('minimum_abs_gap_pct')):
                checks.append({'name': 'Move before the open', 'saw': f"The stock moved {evidence['gap_pct']:+.2f}% from the prior close.",
                    'required': f"The rule required a move of at least {screen['minimum_abs_gap_pct']:g}% in either direction.", 'meaning': 'The move was too small for this setup to qualify.'})
            elif code in ('hourly_alignment_missing_or_opposed', 'ema15_alignment_missing_or_opposed'):
                key = 'hourly_direction' if code.startswith('hourly') else 'ema15_direction'
                checks.append({'name': 'Larger-chart direction', 'saw': f"The saved {'one-hour' if key.startswith('hourly') else '15-minute'} direction was {evidence.get(key) or 'not available'}.",
                    'required': f"It needed to agree with the {row.get('direction')} setup.", 'meaning': 'This rule did not have the matching trend confirmation it required.'})
            else:
                labels = {'premarket_volume_unavailable': 'Reliable premarket volume was unavailable.',
                    'premarket_data_unavailable': 'The premarket data could not be loaded.',
                    'premarket_gap_unavailable': 'The move from the prior close could not be measured.',
                    'gap_direction_mismatch': 'The premarket move opposed the proposed trade direction.',
                    'unknown_direction': 'The trade direction was not recorded reliably.',
                    'prior_daily_range_not_below_atr10_or_missing': 'The prior day did not pass the required range check, or its data was missing.'}
                checks.append({'name': 'Premarket eligibility', 'saw': labels.get(code, 'A saved premarket check failed; its detailed explanation is unavailable.'),
                    'required': 'All required premarket checks must pass.', 'meaning': 'The bot could not approve this setup for an order.'})
    where = []
    if reason == 'premarket_screen_rejected':
        where.append(evidence.get('premarket_window') or 'Premarket window not recorded')
        if evidence.get('premarket_history_sessions'):
            where.append(f"Compared with {evidence['premarket_history_sessions']} earlier sessions")
        if evidence.get('premarket_volume_feed'):
            where.append('Volume source: ' + str(evidence['premarket_volume_feed']))
    elif row.get('trigger_bar'):
        where.append('Signal candle: ' + str(row['trigger_bar']))
    return {'setup': saw, 'checks': checks, 'where': '. '.join(where), 'source': source,
            'recorded_detail': detail or None,
            'conclusion': ('No order was approved: the saved premarket check failed.' if checks else None)}
