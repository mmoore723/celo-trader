"""Order-free worker boundary for the isolated longer-expiration experiment."""
from copy import deepcopy
import logging

import pandas as pd

from auth.context import get_current_user_id
from config.research_snapshot import current_snapshot
from database.connection import get_conn
from database import expiration_study as ledger
from strategy_health.impulse_exit import et
from strategy_health.expiration_study_exits import PROTOCOL_BY_STRATEGY
from trading.expiration_study_selection import PROFILE, PROFILES, select

logger = logging.getLogger('celo_trader.research')


class SharedReads:
    """Bounded per-ticker-pass cache; no orders, account APIs or stale fill reuse.

    Listing data lasts five minutes; chain and quote snapshots five seconds.
    Every selection still revalidates exchange timestamps and setup timeliness.
    Counts are provider-method reads, not claims about underlying HTTP retries.
    """
    def __init__(self, reader, clock):
        self.reader, self.clock = reader, clock
        self.cache = {}
        self.reads = dict(expirations=0, chain=0, quote=0)

    def _read(self, kind, key, ttl, callback):
        now = et(self.clock())
        cached = self.cache.get((kind, key))
        if cached and 0 <= (now-cached[0]).total_seconds() <= ttl:
            if cached[2]:
                raise RuntimeError('Cached provider read unavailable')
            return deepcopy(cached[1])
        self.reads[kind] += 1
        try:
            result = callback()
        except Exception:
            self.cache[(kind, key)] = (et(self.clock()), None, True)
            raise
        self.cache[(kind, key)] = (et(self.clock()), deepcopy(result), False)
        return deepcopy(result)

    def get_research_expiration_details(self, ticker, **kwargs):
        key = (ticker, et(self.clock()).date().isoformat(), tuple(sorted(kwargs.items())))
        return self._read('expirations', key, 300, lambda: self.reader.get_research_expiration_details(ticker, **kwargs))

    def get_research_option_chain(self, ticker, expiry, option_type):
        return self._read('chain', (ticker, expiry, option_type), 5,
                          lambda: self.reader.get_research_option_chain(ticker, expiry, option_type))

    def get_option_quote(self, symbol):
        return self._read('quote', symbol, 5, lambda: self.reader.get_option_quote(symbol))


def _account(settings):
    pinned = current_snapshot(get_current_user_id())
    if pinned is None or not pinned.get('shadow_ledger_enabled', True):
        return None
    identity = lambda s: (s.get('active_broker_account_id') or '', bool(s.get('paper_trading', True)),
                          s.get('broker_provider', 'alpaca'))
    if identity(settings) != identity(pinned):
        return None
    return (pinned.get('active_broker_account_id') or '',)


def observe(*, signal, ticker, price, reader, settings, clock, stopped=lambda: False):
    for profile in PROFILES:
        _observe_profile(signal=signal, ticker=ticker, price=price, reader=reader,
                         settings=settings, clock=clock, stopped=stopped, profile=profile)


def _observe_profile(*, signal, ticker, price, reader, settings, clock, stopped, profile):
    """Called only after primary observation; never backfill historical setups."""
    scope = _account(settings)
    meta = getattr(signal, 'meta', {})
    sid = str(getattr(signal, 'strategy_id', ''))
    if (scope is None or stopped() or sid not in PROTOCOL_BY_STRATEGY or not isinstance(meta, dict)
            or meta.get('research_existing_candidate') or not meta.get('shadow_candidate_id')):
        return
    candidate_id = meta['shadow_candidate_id']
    with get_conn() as conn:
        row = conn.execute('''SELECT s.observed_at,s.trigger_bar,s.strategy_id,s.ticker,s.direction FROM shadow_candidates s
            WHERE s.candidate_id=? AND COALESCE(s.broker_account_id,'')=?
            AND NOT EXISTS (SELECT 1 FROM research_expiration_comparisons e
                WHERE e.candidate_id=s.candidate_id AND e.profile_version=?)''',
            (candidate_id, scope[0], profile)).fetchone()
    if (row is None or row['strategy_id'] != sid or row['ticker'] != ticker
            or row['direction'] != getattr(signal, 'direction', None)):
        return
    before = dict(reader.reads)
    selection = select(reader, ticker=ticker, direction=row['direction'], underlying_price=price,
                       setup_at=row['trigger_bar'], clock=clock, profile=profile)
    selection['observed_at'] = row['observed_at']
    selection['capture_revision'] = 'signal_time_validation_v2'
    selection['provider_reads'] = {key: reader.reads[key]-before[key] for key in before}
    if stopped():
        return
    with get_conn() as conn:
        ledger.record(conn, account=scope[0], candidate_id=candidate_id, selection=selection)


def capture(*, market, options, settings, worker_state, stopped, clock):
    """The worker's pinned settings keep every connection in its original DB."""
    scope = _account(settings)
    if scope is None or stopped():
        return
    from signals import bars_to_df
    def bars(ticker):
        from trading.research_bar_capture import session_frame
        return session_frame(market, options, ticker, account=scope[0], clock=clock)
    def native_bars(ticker):
        from trading.research_ema_history import native_ema_history
        frame = native_ema_history(market, ticker, worker_state, clock(), scope[0]).copy()
        frame.attrs['source_minutes'] = 15
        return frame
    stats = ledger.capture(connect=get_conn, account=scope[0], bars_lookup=bars,
                           quote_lookup=options.get_option_quote, clock=clock,
                           stopped=stopped, ema_bars_lookup=native_bars)
    if stats['rows']:
        logger.info('expiration_study_exit rows=%d bars_reads=%d quote_reads=%d failed_rows=%d',
                    stats['rows'], stats['bars_reads'], stats['quote_reads'], stats['failed_rows'])
    return stats
