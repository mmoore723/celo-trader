"""
trading/entry/contract.py — Option contract selection.

Split out of trading/entry.py (2026-08-01, file-size cleanup); no logic
changed, only relocated. select_contract() is shared by the real entry
path (trading/entry/tick.py) and api/routes/signals.py's
resolve_watching_contracts() (display refresh only, for_display=True) --
both call sites verified to still resolve correctly after this split.
"""

from __future__ import annotations

import logging
from typing import Optional, Tuple

from broker import TradierClient
from config import MIN_CONTRACT_COST, MAX_CONTRACT_COST, MIN_OPEN_INTEREST, get_settings

logger = logging.getLogger("celo_trader.trading_logic")


def select_contract(
    tradier: TradierClient,
    ticker: str,
    direction: str,
    current_price: float,
    max_spend: float,
    for_display: bool = False,
) -> Tuple[Optional[dict], dict]:
    """
    Select the best option contract for entry.

    Contract filters (in order):
      1. First OTM strike (call: above price, put: below price)
      2. ask between MIN_CONTRACT_COST ($0.05) and MAX_CONTRACT_COST ($10.00)
      3. ask × 100 ≤ max_spend (position dollar limit from settings)
      4. bid-ask spread ≤ the user's spread_gate_pct of mid price
      5. open_interest ≥ MIN_OPEN_INTEREST (100)

    Returns (contract, info) where info["reason"] is one of:
      "selected", "api_error", "no_expirations", "no_chain_data",
      "over_budget", "illiquid", "filtered"

    2026-07-24: previously any candidate that passed the cost check but then
    failed the spread or OI check just silently `continue`d — invisible.
    So "over_budget" could be misleading: it only proves the CHEAPEST
    cost-rejected candidate was too expensive, not that no affordable
    candidate existed at all. If a candidate was cost-affordable but got
    rejected for spread/OI, that's a liquidity problem, not a budget
    problem, and the account size isn't actually the blocker — this is
    now tracked separately as info["illiquid_cost"]/["illiquid_symbol"]/
    ["illiquid_fail"] and takes priority in the final reason when found,
    since it's the more accurate diagnosis. See signal_journal.py's
    "illiquid" reason code, added alongside this.

    FIX 2026-07-31: this function is shared by the real entry path
    (trading/entry.py's own call, below) AND resolve_watching_contracts()
    (api/routes/signals.py — called every poll to refresh the live bid/ask
    shown on Watching/Board cards, no trade intent at all). Both used to log
    an identical "Contract selected: ..." INFO line, so the Log tab showed
    what looked like repeated real trade attempts on tickers that were
    never actually being evaluated for entry — real incident: user saw
    "Contract selected: PLTR/SMCI/SPY..." firing every ~1s and assumed the
    bot was finding and abandoning trades. `for_display=True` (passed by
    resolve_watching_contracts) downgrades that line to DEBUG so it stops
    polluting the live-trade narration; the real entry path is unaffected.
    """
    option_type = "call" if direction == "bullish" else "put"
    info = {
        "reason": "no_chain_data",
        "cheapest_cost": None, "cheapest_symbol": None,
        "illiquid_cost": None, "illiquid_symbol": None, "illiquid_fail": None,
    }

    try:
        expirations = tradier.get_expirations(ticker)
    except Exception as ex:
        logger.warning("get_expirations(%s) raised: %s — skipping contract selection", ticker, ex)
        info["reason"] = "api_error"
        return None, info

    if not expirations:
        logger.debug("No expirations returned for %s", ticker)
        info["reason"] = "no_expirations"
        return None, info

    try:
        _spread_max_pct = float(get_settings().get("spread_gate_pct", 8)) / 100.0
    except (TypeError, ValueError):
        _spread_max_pct = 0.08
    _spread_max_pct = min(max(_spread_max_pct, 0.01), 1.0)

    saw_chain_data = False

    for expiry in expirations:
        try:
            chain = tradier.get_option_chain(ticker, expiry, option_type)
        except Exception as ex:
            logger.debug("get_option_chain(%s %s %s) raised: %s", ticker, expiry, option_type, ex)
            continue
        if not chain:
            continue
        saw_chain_data = True

        if option_type == "call":
            candidates = sorted([c for c in chain if c["strike"] > current_price],
                                 key=lambda x: x["strike"])
        else:
            candidates = sorted([c for c in chain if c["strike"] < current_price],
                                 key=lambda x: x["strike"], reverse=True)

        for contract in candidates:
            ask    = contract.get("ask", 0)
            bid    = float(contract.get("bid", 0) or 0)
            spread = float(contract.get("spread", 999) or 999)
            oi     = contract.get("open_interest", 0)

            if ask < MIN_CONTRACT_COST:
                logger.debug("Skip %s — ask $%.2f below min $%.2f",
                             contract.get("symbol","?"), ask, MIN_CONTRACT_COST)
                continue
            if ask > MAX_CONTRACT_COST:
                logger.debug("Skip %s — ask $%.2f above max $%.2f",
                             contract.get("symbol","?"), ask, MAX_CONTRACT_COST)
                continue
            cost = ask * 100
            if cost > max_spend:
                logger.debug("Skip %s — cost $%.0f exceeds max_spend $%.0f",
                             contract.get("symbol","?"), cost, max_spend)
                if info["cheapest_cost"] is None or cost < info["cheapest_cost"]:
                    info["cheapest_cost"]   = cost
                    info["cheapest_symbol"] = contract.get("symbol", "?")
                info["reason"] = "over_budget"
                continue
            # Use the same percentage-of-mid rule the Settings page and the
            # post-selection entry gate expose.  Previously selection used a
            # separate 15%-of-ask rule, so an 8% UI setting could still select
            # a contract that the entry path immediately rejected.
            _spread = max(ask - bid, spread) if bid > 0 else spread
            _mid = (ask + bid) / 2 if bid > 0 else 0.0
            _spread_pct = _spread / _mid if _mid > 0 else float("inf")
            if _spread_pct > _spread_max_pct:
                logger.debug("Skip %s — spread %.1f%% > %.1f%% of mid",
                             contract.get("symbol", "?"), _spread_pct * 100,
                             _spread_max_pct * 100)
                if info["illiquid_cost"] is None or cost < info["illiquid_cost"]:
                    info["illiquid_cost"]   = cost
                    info["illiquid_symbol"] = contract.get("symbol", "?")
                    info["illiquid_fail"] = (
                        f"spread {_spread_pct * 100:.1f}% > "
                        f"{_spread_max_pct * 100:.0f}% max of mid"
                    )
                continue
            if oi < MIN_OPEN_INTEREST:
                logger.debug("Skip %s — OI %d < min %d",
                             contract.get("symbol","?"), oi, MIN_OPEN_INTEREST)
                if info["illiquid_cost"] is None or cost < info["illiquid_cost"]:
                    info["illiquid_cost"]   = cost
                    info["illiquid_symbol"] = contract.get("symbol", "?")
                    info["illiquid_fail"]   = f"open interest {oi} < {MIN_OPEN_INTEREST} min"
                continue

            contract["expiry"] = expiry
            _log_fn = logger.debug if for_display else logger.info
            _log_fn(
                "Contract selected: %s exp=%s strike=%.2f ask=%.2f spread=%.2f OI=%d%s",
                contract["symbol"], expiry, contract["strike"],
                ask, spread, oi, " (display refresh, not an entry)" if for_display else "",
            )
            info["reason"] = "selected"
            return contract, info

    if not saw_chain_data:
        info["reason"] = "no_chain_data"
    elif info["illiquid_cost"] is not None:
        # An affordable contract existed but got rejected on liquidity, not
        # cost — more accurate than "over_budget" when both occurred, since
        # the account size wasn't actually the blocker here.
        info["reason"] = "illiquid"
    elif info["cheapest_cost"] is None:
        info["reason"] = "filtered"

    return None, info
