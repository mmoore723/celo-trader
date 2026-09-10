"""Order-free watchlist collection and the existing prospective observers."""
import logging
from inspect import getattr_static
from time import monotonic
from types import SimpleNamespace

import pandas as pd

from auth.context import get_current_user_id
from config.strategy_catalog import (
    enabled_observation_strategy_ids,
    reviewed_execution_strategy_ids,
)
from database import load_scanner_candles, record_scanner_candles
from database.option_quotes import capture_due_candidate_option_quotes
from database.research_exits import capture_authored_exits
from database.option_profit_protection import capture as capture_profit_protection
from shadow_ledger import mark_candidate_observed_only
from signals import bars_to_df
from strategy_router import route_signals
from trading.entry.candidate_observation import observe_candidate_contract
from trading.entry.injected_setups import evaluate_injected_setups
from trading.observers.qqq_opening_downmove import maybe_observe
from trading.state import _now_et
from trading.tested_strategy_research import (
    enabled_tested_research_ids, evaluate_tested_research,
)

logger = logging.getLogger("celo_trader.research")


def market_readers(alpaca, tradier):
    """Expose only named reads; neither object can submit/cancel/manage orders."""
    option_reads = {name: getattr(tradier, name) for name in (
        "get_option_quote", "get_expirations", "get_option_chain",
    )}
    if callable(getattr_static(tradier, "get_research_option_chain", None)):
        option_reads["get_research_option_chain"] = tradier.get_research_option_chain
    return (
        SimpleNamespace(**{name: getattr(alpaca, name) for name in (
            "get_session_bars", "get_bars", "get_latest_quote", "is_market_open",
        )}),
        SimpleNamespace(**option_reads),
    )


def observe_ticker(alpaca, tradier, ticker, settings, state, risk, balance, stopped):
    bars, error, _ = alpaca.get_session_bars(ticker, "1Min")
    if stopped() or error or not bars:
        return
    current = bars_to_df(bars)
    account = settings.get("active_broker_account_id") or None
    record_scanner_candles(ticker, current, broker_account_id=account)
    if not settings.get("shadow_ledger_enabled", True):
        return
    observed = enabled_observation_strategy_ids(settings, ticker=ticker)
    # Native trading pairs also need the separate, uncapped research path.
    # All IDs stay observation-only here; the router receives no order IDs.
    observed |= reviewed_execution_strategy_ids()
    tested_ids = enabled_tested_research_ids(settings)
    if observed or tested_ids:
        frame = current
        history, error = alpaca.get_bars(ticker, "5Min", limit=1500)
        history_5m = bars_to_df(history) if history and not error else None
        if stopped():
            return
        if history and not error:
            prior = bars_to_df(history)
            prior = prior[prior["time"] < current["time"].min()]
            if not prior.empty:
                frame = pd.concat([prior, current], ignore_index=True).sort_values("time").reset_index(drop=True)
        injected, _, _ = evaluate_injected_setups(
            state, current, ticker, set(), observed, alpaca, settings,
        )
        if stopped():
            return
        cache = {}

        def record(symbol, signal, price):
            if not stopped():
                observe_candidate_contract(
                    ticker=symbol, signal=signal, underlying_price=price,
                    tradier=tradier, balance=balance, risk=risk, settings=settings,
                    selection_cache=cache, research_only=True,
                )

        # Never call _tick or return these signals to the trading loop.
        observation_scope = (
            f"research_worker:{get_current_user_id()}:{account}:"
            f"{settings.get('paper_trading', True)}"
        )
        returned = route_signals(
            frame, ticker, enabled_strategies=set(), quiet=True,
            candidate_observer=record, observation_only_strategies=observed,
            observation_resolver=mark_candidate_observed_only,
            injected_signals=injected, preserve_reviewed_paid_rules=True,
            observation_scope=observation_scope,
        )
        if returned:
            raise RuntimeError("Observation router unexpectedly returned executable signals")
        tested_frame = load_scanner_candles(
            ticker, broker_account_id=account, timeframe="1Min", limit=10_000,
        )
        if tested_frame.empty:
            tested_frame = current
        native_15m=None
        if 'V2_EMA_PULLBACK_RTH' in tested_ids:
            from trading.research_ema_history import native_ema_history
            native_15m=native_ema_history(alpaca,ticker,state,_now_et(),account,
                archive=lambda f: record_scanner_candles(ticker,f,broker_account_id=account,
                                                       timeframe='15Min',source='alpaca_iex_native15'))
        if stopped():
            return
        for signal in evaluate_tested_research(
            tested_frame, ticker, tested_ids, scope=observation_scope, now=_now_et(), history_5m=history_5m,
            history_15m=native_15m,
        ):
            record(ticker, signal, float(current["close"].iloc[-1]))
            mark_candidate_observed_only(signal)
    if not stopped():
        capture_due_candidate_option_quotes(
            ticker=ticker, observed_at=_now_et(), quote_lookup=tradier.get_option_quote,
            broker_account_id=account,
        )
    logger.info(
        "research_scan ticker=%s archived_bars=%d observer_count=%d tested_count=%d",
        ticker, len(current), len(observed), len(tested_ids),
    )


def run_research_pass(readers, snapshot, state, stopped):
    alpaca, tradier = readers
    if stopped():
        return
    def profit_bars(ticker):
        bars, error, _ = alpaca.get_session_bars(ticker, '1Min')
        return bars_to_df(bars) if bars and not error else pd.DataFrame()

    def profit_checkpoint(force=False):
        if not snapshot['settings'].get('shadow_ledger_enabled', True) or stopped():
            return
        now = monotonic()
        if not force and now-state.get('profit_checkpoint_at', -float('inf')) < 30:
            return
        state['profit_checkpoint_at'] = now
        try:
            capture_profit_protection(account=snapshot['settings'].get('active_broker_account_id'),
                                      quote_lookup=tradier.get_option_quote, bars_lookup=profit_bars,
                                      stopped=stopped, clock=_now_et)
        except Exception:
            logger.warning('Profit-protection checkpoint failed; research continues', exc_info=True)

    profit_checkpoint(force=True)
    # Pending exits have priority over the expensive all-ticker signal replay.
    # Include the close so 15:55 candles can decide at 16:00, without new entries.
    if snapshot["settings"].get("shadow_ledger_enabled", True):
        def exit_bars(ticker):
            bars, error, _ = alpaca.get_session_bars(ticker, "1Min")
            return bars_to_df(bars) if bars and not error else pd.DataFrame()

        def ema_exit_bars(ticker):
            from trading.research_ema_history import native_ema_history
            account=snapshot['settings'].get('active_broker_account_id')
            frame=native_ema_history(alpaca,ticker,state,_now_et(),account,
                archive=lambda f: record_scanner_candles(ticker,f,broker_account_id=account,
                                                       timeframe='15Min',source='alpaca_iex_native15')).copy()
            frame.attrs['source_minutes']=15
            return frame

        try:
            capture_authored_exits(
                account=snapshot["settings"].get("active_broker_account_id"),
                bars_lookup=exit_bars, quote_lookup=tradier.get_option_quote,
                stopped=stopped, clock=_now_et,
                ema_bars_lookup=ema_exit_bars,
            )
        except Exception:
            logger.warning("Authored exit pass failed; research continues", exc_info=True)
    if stopped() or not alpaca.is_market_open():
        return
    for ticker in snapshot["tickers"]:
        if stopped():
            break
        profit_checkpoint()
        try:
            observe_ticker(alpaca, tradier, ticker, snapshot["settings"], state,
                           snapshot["risk"], snapshot["balance"], stopped)
        except Exception:
            logger.warning("Research scan failed for %s; continuing other tickers", ticker, exc_info=True)
    profit_checkpoint()
    if not stopped():
        maybe_observe(alpaca, tradier)
