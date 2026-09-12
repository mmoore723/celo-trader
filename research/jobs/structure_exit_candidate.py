"""Frozen research-only exit candidate. No broker or production imports.

Protocol structure_retest_v1: initial thesis stop from the entry, two completed
1m closes for a retest, tighten behind a confirmed pivot after 1R, and exit a
failed break/retest or opposing volume/momentum at resistance. Evaluate 1/5/15/60m
completed bars. A separate 20% option-premium loss guard has priority. Preserve
the original 30/90m time cap for the first paired comparison to isolate exits.
The prior standalone 20% experiment failed; this combination is NOT validated.

Test plan: unit coverage for direction symmetry, retest/reclaim, never loosening
protection, loss guard, timer, missing frames, duplicates and future-bar isolation;
paired replay on every retained entry, reproduce control bids/costs, report
unpaired/missing evidence, damaged winners and portfolio effects separately.
No parameter sweep or production routing is authorized by this module.
"""
from bisect import bisect_right
from dataclasses import dataclass
from datetime import datetime, timedelta, time
import math
from zoneinfo import ZoneInfo

from research.engine.data import resample_regular_session
from research.engine.models import Bar

PROTOCOL = 'structure_retest_v1'
ET = ZoneInfo('America/New_York')


def ema(values, period):
    result = [values[0]]
    alpha = 2 / (period + 1)
    for x in values[1:]:
        result.append(alpha*x + (1-alpha)*result[-1])
    return result


def frame(bars):
    if len(bars) < 35:
        return None
    closes = [b.close for b in bars]
    fast, slow = ema(closes, 9)[-1], ema(closes, 20)[-1]
    macd = [a-b for a,b in zip(ema(closes, 12), ema(closes, 26))]
    signal = ema(macd, 9)
    changes = [b-a for a,b in zip(closes, closes[1:])]
    gains = sum(max(x, 0) for x in changes[:14])/14
    losses = sum(max(-x, 0) for x in changes[:14])/14
    for x in changes[14:]:
        gains = (13*gains+max(x, 0))/14
        losses = (13*losses+max(-x, 0))/14
    rsi = 100*gains/(gains+losses) if gains+losses else 50
    return dict(close=closes[-1], fast=fast, slow=slow,
                histogram=macd[-1]-signal[-1],
                histogram_change=(macd[-1]-signal[-1])-(macd[-2]-signal[-2]), rsi=rsi)


class MarketContext:
    """Preaggregate history, but expose each bucket only AFTER its close.

    Missing 1m constituents discard the whole higher-timeframe bucket.
    UTC input is converted to exchange time before session anchoring.
    """
    def __init__(self, bars):
        normalized = []
        prior = None
        for b in bars:
            if b.timestamp.tzinfo is None:
                raise ValueError('Timezone required')
            if prior is not None and b.timestamp <= prior:
                raise ValueError('Bars must be unique and ordered')
            prior = b.timestamp
            values = (b.open, b.high, b.low, b.close, b.volume)
            if not all(math.isfinite(x) for x in values) or b.low <= 0 or b.volume < 0:
                raise ValueError('Invalid candle')
            if not b.low <= min(b.open, b.close) <= max(b.open, b.close) <= b.high:
                raise ValueError('Invalid candle range')
            stamp = b.timestamp.astimezone(ET)
            if stamp.second or stamp.microsecond:
                raise ValueError('Minute-open timestamps required')
            if time(9,30) <= stamp.time() <= time(15,59):
                normalized.append(Bar(stamp, *values))
        self.frames = {n:resample_regular_session(tuple(normalized), 1, n) for n in (1,5,15,60)}
        self.ends = {n:[b.timestamp+timedelta(minutes=n) for b in rows]
                     for n,rows in self.frames.items()}

    def at(self, now):
        if now.tzinfo is None:
            raise ValueError('Timezone required')
        histories = {n:rows[max(0, bisect_right(self.ends[n], now)-100):bisect_right(self.ends[n], now)]
                     for n,rows in self.frames.items()}
        one = histories[1]
        if not one or one[-1].timestamp+timedelta(minutes=1) != now:
            raise ValueError('Missing completed one-minute candle')
        # A gap is not a valid contiguous candle sequence for a retest.
        recent = one[-20:]
        if len(recent) < 20 or any(b.timestamp-a.timestamp != timedelta(minutes=1)
                                 for a,b in zip(recent, recent[1:])):
            raise ValueError('Missing recent one-minute history')
        supports, resistances = [], []
        for i in range(2, len(recent)-2):
            window = recent[i-2:i+3]
            b = recent[i]
            if b.low == min(x.low for x in window) and sum(x.low == b.low for x in window) == 1:
                supports.append(b.low)
            if b.high == max(x.high for x in window) and sum(x.high == b.high for x in window) == 1:
                resistances.append(b.high)
        prior_volume = sum(b.volume for b in recent[:-1])/19
        last = one[-1]
        return dict(time=now, close=last.close, open=last.open,
                    relative_volume=last.volume/prior_volume if prior_volume else None,
                    supports=supports, resistances=resistances,
                    frames={n:frame(rows) for n,rows in histories.items()})


@dataclass
class ExitState:
    direction: int
    stock_entry: float
    initial_stop: float
    option_ask: float
    entry_time: datetime
    cap_minutes: int
    protection: float | None = None
    broken_at: datetime | None = None
    last_time: datetime | None = None
    exit_reason: str | None = None

    def __post_init__(self):
        if (self.direction not in (-1,1) or self.cap_minutes <= 0
                or not all(math.isfinite(x) and x > 0 for x in
                           (self.stock_entry, self.initial_stop, self.option_ask))
                or self.direction*(self.stock_entry-self.initial_stop) <= 0
                or self.entry_time.tzinfo is None):
            raise ValueError('Invalid entry thesis')
        self.protection = self.initial_stop

    def step(self, context, option_bid):
        now = context['time']
        if now <= self.entry_time or (self.last_time and now <= self.last_time):
            raise ValueError('Exit decisions must advance after entry')
        if not math.isfinite(option_bid) or option_bid <= 0:
            raise ValueError('Valid same-contract bid required')
        if self.exit_reason:
            raise ValueError('Already exited')
        self.last_time = now
        reason = None
        action = 'hold'
        d, close = self.direction, context['close']
        if option_bid <= self.option_ask*.80:
            reason = 'maximum_premium_loss_20pct'
        elif now >= self.entry_time+timedelta(minutes=self.cap_minutes):
            reason = 'original_time_cap'
        else:
            frames = context['frames']
            one = frames.get(1)
            higher = [frames.get(n) for n in (5,15,60)]
            # Missing indicators are unknown, never fabricated agreement.
            if one is None or any(x is None for x in higher):
                return dict(action='missing_context', reason='higher_timeframe_warmup', protection=self.protection)
            aligned = sum(d*(x['fast']-x['slow']) > 0 and d*(x['close']-x['slow']) > 0 for x in higher)
            opposing = (d*(one['fast']-one['slow']) < 0
                        and d*one['histogram'] < 0 and d*(one['rsi']-50) < 0)
            high_volume = context['relative_volume'] is not None and context['relative_volume'] >= 1.5
            opposing_candle = d*(close-context['open']) < 0
            broken = d*(close-self.protection) < 0
            if broken:
                self.broken_at = self.broken_at or now
                if aligned < 2 and opposing and high_volume:
                    reason = 'structure_failed_with_opposing_volume'
                elif now-self.broken_at >= timedelta(minutes=2):
                    reason = 'structure_retest_failed'
                else:
                    action = 'allow_retest'
            else:
                self.broken_at = None
                risk = abs(self.stock_entry-self.initial_stop)
                if d*(close-self.stock_entry) >= risk:
                    levels = context['supports'] if d == 1 else context['resistances']
                    eligible = [x for x in levels if d*(x-self.protection)>0 and d*(close-x)>0]
                    if eligible:
                        self.protection = max(eligible) if d == 1 else min(eligible)
                        action = 'tighten'
                    barriers = context['resistances'] if d == 1 else context['supports']
                    near_barrier = any(0 <= d*(x-close) <= risk*.25 for x in barriers)
                    fading = d*one['histogram_change'] < 0 and d*(one['rsi']-50) < 0
                    if near_barrier and fading and opposing_candle and high_volume:
                        reason = 'resistance_rejection_with_fading_momentum'
        if reason:
            self.exit_reason = reason
        return dict(action='exit' if reason else action, reason=reason, protection=self.protection)
