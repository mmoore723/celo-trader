from datetime import datetime, timedelta
import logging
from zoneinfo import ZoneInfo

ET = ZoneInfo('America/New_York')
logger = logging.getLogger('celo_trader.trading_logic')


def session_close_if_open(client, now):
    now = now.replace(tzinfo=ET) if now.tzinfo is None else now.astimezone(ET)
    cached = getattr(client, '_research_session_clock_cache', None)
    if isinstance(cached, dict) and cached['checked'] <= now < cached['until']:
        close = cached['close']
        return close if close and now < close else None
    close = None
    try:
        if getattr(client, 'provider', None) == 'tradier':
            data = client.market._get('/markets/clock')['clock']
            observed = datetime.fromtimestamp(data['timestamp'], ET)
            opened = data['state'] == 'open'
            if opened:
                close = datetime.fromisoformat(data['date'] + 'T' + data['next_change']).replace(tzinfo=ET)
        else:
            data = client._get(client.base + '/v2/clock')
            observed = datetime.fromisoformat(data['timestamp'].replace('Z', '+00:00'))
            opened = data['is_open'] is True
            if opened:
                close = datetime.fromisoformat(data['next_close'].replace('Z', '+00:00')).astimezone(ET)
        if observed.tzinfo is None or not -5 <= (now - observed).total_seconds() <= 30:
            raise ValueError('Stale or timezone-free broker clock')
        if close and (close.date() != now.date() or close <= now):
            raise ValueError('Invalid broker session close')
    except Exception:
        close = None
        logger.warning('Research exit waiting for a fresh open broker session', exc_info=True)
    client._research_session_clock_cache = {
        'checked': now, 'until': now + timedelta(seconds=5 if close else 30), 'close': close}
    return close
