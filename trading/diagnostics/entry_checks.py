"""Observational check capture, scoped to one actual strategy evaluation.

Does not re-evaluate strategies or decide orders. Later evaluations replace
previous observations so historical replay cannot leak an old passing check.
"""
from contextlib import contextmanager
from contextvars import ContextVar
import logging

_current = ContextVar('entry_checks', default=None)


def record_checks(checks):
    target = _current.get()
    if target is not None:
        target[:] = checks


@contextmanager
def capture_checks(strategy_id, ticker, enabled=True):
    values = [] if enabled else None
    token = _current.set(values)
    try:
        yield
    except BaseException:
        if values is not None:
            values.clear()
        raise
    finally:
        _current.reset(token)
        if values:
            try:
                pending = next((c for c in values if c.get('status') == 'pending'), None)
                failed = next((c for c in values if c.get('passed') is False), None)
                unknown = next((c for c in values if c.get('status') == 'unknown'), None)
                message = (failed or pending or unknown or {}).get('reason') or 'Recorded chart checks passed. Order safeguards still apply.'
                logging.getLogger('celo_trader.bar_eval').info(message, extra={
                    'event': 'strategy_entry_checks', 'strategy_id': strategy_id,
                    'ticker': ticker, 'checks': values,
                })
            except Exception:
                # A display diagnostic must never interrupt execution.
                pass


def active():
    return _current.get() is not None


def add_check(name, passed=None, reason='', *, pending=False):
    """Append/replace a measured check without changing its caller's result."""
    target = _current.get()
    if target is None:
        return
    item = {'name': name, 'reason': reason}
    if passed is not None:
        item['passed'] = bool(passed)
    else:
        item['status'] = 'pending' if pending else 'unknown'
    target[:] = [old for old in target if old.get('name') != name] + [item]


def library_checks(strategy, bars):
    """Read-only VWAP display using the configured evaluator's same bar helpers.

    Run only on the final replay bar, never on the background research path.
    Diagnostics cannot change the engine, its state, or its returned signal.
    """
    if not active() or not bars or getattr(strategy, 'strategy_id', '') != 'V2_VWAP_PULLBACK':
        return
    try:
        from datetime import time
        from research.engine.strategies.vwap_pullback import _session, _vwaps
        from research.engine.strategies.trend_continuation import _ema
        today = _session(bars)
        c = strategy.config
        minimum = max(c.slow_ema, c.atr_bars + 1, c.slope_bars + 2)
        if len(today) < minimum or today[-1].timestamp.time() < time(9,45):
            add_check('Completed candles', reason=f'{len(today)} available; need {minimum} and 9:45 AM or later.', pending=True)
            return
        vwaps = _vwaps(today)
        current, prior = today[-1], today[-2]
        cv, pv = vwaps[-1], vwaps[-2]
        closes = [b.close for b in today[-c.slow_ema:]]
        fast, slow = _ema(closes[-c.fast_ema:],c.fast_ema), _ema(closes,c.slow_ema)
        bullish = fast > slow
        direction = 'Call' if bullish else 'Put'
        add_check(f'EMA {c.fast_ema}/{c.slow_ema}', fast != slow,
                  f'{direction} direction: fast average ${fast:.2f}, slow ${slow:.2f}.')
        add_check('VWAP slope', cv > vwaps[-1-c.slope_bars] if bullish else cv < vwaps[-1-c.slope_bars],
                  f'VWAP ${cv:.2f}; earlier ${vwaps[-1-c.slope_bars]:.2f}.')
        count = sum(b.close > v if bullish else b.close < v for b,v in zip(today[-7:-2],vwaps[-7:-2]))
        add_check('4/5 closes', count >= 4, f'{count} of 5 earlier closes are on the {direction.lower()} side of VWAP.')
        tolerance = pv*c.touch_tolerance_pct
        add_check('VWAP touch', abs((prior.low if bullish else prior.high)-pv)<=tolerance,
                  f'Previous candle must reach within ${tolerance:.2f} of VWAP ${pv:.2f}.')
        add_check('Reclaim' if bullish else 'Rejection', current.close>cv if bullish else current.close<cv,
                  f'Completed close ${current.close:.2f}; VWAP ${cv:.2f}.')
    except Exception:
        record_checks([{'name':'Chart checks','status':'unknown','reason':'Check details could not be recorded for this candle.'}])


def finish_checks(signal):
    target = _current.get()
    if target and signal is None and all(c.get('passed') is True or c.get('status') == 'passed' for c in target):
        add_check('Entry signal', False, 'These chart checks passed, but the evaluator did not return a new entry. Freshness and duplicate-setup rules still apply.')
