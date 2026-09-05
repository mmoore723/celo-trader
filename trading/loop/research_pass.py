"""Order-free watchlist collection and the existing prospective observers."""
import logging
from types import SimpleNamespace

import pandas as pd

from auth.context import get_current_user_id
from config.strategy_catalog import (
    enabled_observation_strategy_ids, enabled_reviewed_strategy_ids,
    reviewed_execution_strategy_ids,
)
from database import record_scanner_candles
from database.option_quotes import capture_due_candidate_option_quotes
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
    return (
        SimpleNamespace(**{name: getattr(alpaca, name) for name in (
            "get_session_bars", "get_bars", "get_latest_quote", "is_market_open",
        )}),
        SimpleNamespace(**{name: getattr(tradier, name) for name in (
            "get_option_quote", "get_expirations", "get_option_chain",
        )}),
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
    enabled = enabled_reviewed_strategy_ids(settings, ticker=ticker)
    observed = enabled_observation_strategy_ids(settings, ticker=ticker)
    # Every reviewed execution rule keeps researching the rest of the scanner
    # universe. Trading scope and research scope must never be the same list.
    observed |= reviewed_execution_strategy_ids() - enabled
    tested_ids = enabled_tested_research_ids(settings)
    if observed or tested_ids:
        frame = current
        history, error = alpaca.get_bars(ticker, "5Min", limit=1500)
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
        for signal in evaluate_tested_research(
            frame, ticker, tested_ids, scope=observation_scope, now=_now_et(),
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
    if stopped() or not alpaca.is_market_open():
        return
    for ticker in snapshot["tickers"]:
        if stopped():
            break
        try:
            observe_ticker(alpaca, tradier, ticker, snapshot["settings"], state,
                           snapshot["risk"], snapshot["balance"], stopped)
        except Exception:
            logger.warning("Research scan failed for %s; continuing other tickers", ticker, exc_info=True)
    if not stopped():
        maybe_observe(alpaca, tradier)
