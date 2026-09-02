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
from datetime import date
from typing import Optional, Tuple

from broker import TradierClient
from config import MIN_CONTRACT_COST, MAX_CONTRACT_COST, MIN_OPEN_INTEREST, get_settings
from trading.state import _now_et

logger = logging.getLogger("celo_trader.trading_logic")


# These are the contract bounds used in the paid TSLA V2 ORB study.  They are
# deliberately separate from the generic selector below: changing the latter
# would silently alter every existing strategy.  The V2 function is called
# only for a paper trade whose strategy ID is V2_ORB_PULLBACK.
V2_ORB_PAPER_MIN_DTE = 7
V2_ORB_PAPER_MAX_DTE = 21
V2_ORB_PAPER_MIN_PREMIUM = 0.80
V2_ORB_PAPER_MAX_PREMIUM = 10.00
V2_ORB_PAPER_MAX_SPREAD_PCT = 0.08


def _reviewed_contract_shadow_leaderboard(
    candidates: list[tuple[int, float, float, str, dict]],
) -> list[dict]:
    """Return policy winners for research without influencing execution.

    The reviewed selector intentionally remains nearest expiry, then nearest
    OTM strike.  This compact leaderboard preserves the alternatives that used
    to disappear after selection, allowing later quote/fill studies to compare
    concrete policies rather than inventing them after the fact.
    """
    if not candidates:
        return []
    policies = {
        "reviewed_nearest_expiry_otm": lambda item: item[:4],
        "tightest_spread": lambda item: (item[2], item[0], item[1], item[3]),
        "lowest_ask": lambda item: (float(item[4].get("ask") or float("inf")), item[0], item[1], item[3]),
        "highest_open_interest": lambda item: (-float(item[4].get("open_interest") or 0), item[2], item[0], item[3]),
        "highest_volume": lambda item: (-float(item[4].get("volume") or 0), item[2], item[0], item[3]),
        "closest_otm_strike": lambda item: (item[1], item[0], item[2], item[3]),
        "closest_to_14_dte": lambda item: (abs(item[0] - 14), item[1], item[2], item[3]),
    }
    winners: dict[str, dict] = {}
    for policy, key in policies.items():
        dte, distance, spread_pct, symbol, contract = min(candidates, key=key)
        row = winners.setdefault(symbol, {
            "symbol": symbol,
            "expiry": contract.get("expiry"),
            "dte": int(dte),
            "strike": float(contract.get("strike") or 0),
            "otm_distance": round(float(distance), 4),
            "bid": float(contract.get("bid") or 0),
            "ask": float(contract.get("ask") or 0),
            "spread_pct": round(float(spread_pct), 6),
            "volume": int(float(contract.get("volume") or 0)),
            "open_interest": int(float(contract.get("open_interest") or 0)),
            "policy_winner_for": [],
        })
        row["policy_winner_for"].append(policy)
    return sorted(
        winners.values(),
        key=lambda row: ("reviewed_nearest_expiry_otm" not in row["policy_winner_for"], row["symbol"]),
    )


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


def select_reviewed_v2_contract(
    tradier: TradierClient,
    ticker: str,
    direction: str,
    current_price: float,
    max_spend: float,
    for_display: bool = False,
) -> Tuple[Optional[dict], dict]:
    """Select the locked paid-quote contract profile for a reviewed ticker.

    The paid historical study used the nearest eligible expiry (7--21 DTE),
    the closest *out-of-the-money* strike, a $0.80--$10.00 ask, and a maximum
    8% bid/ask spread measured against mid.  This function applies those same
    observable rules to the broker chain at entry time.  It does not loosen
    the account's position-budget cap.  The policy is deliberately independent
    of paper/live mode: paper evidence must exercise the same contract
    definition that a later, explicitly approved live promotion would use.
    Tradier's chain client also removes obviously invalid/illiquid rows
    upstream; that limitation is returned in the audit metadata rather than
    hidden.
    """
    ticker = ticker.strip().upper()
    selection_model = (
        "v2_orb_paid_tsla_near_money_otm_v1"
        if ticker == "TSLA" else "v2_spy_trend_paid_near_money_otm_v1"
    )
    info: dict = {
        "reason": "no_chain_data",
        "selection_model": selection_model,
        "research_eligibility": {
            "min_dte": V2_ORB_PAPER_MIN_DTE,
            "max_dte": V2_ORB_PAPER_MAX_DTE,
            "min_premium": V2_ORB_PAPER_MIN_PREMIUM,
            "max_premium": V2_ORB_PAPER_MAX_PREMIUM,
            "max_spread_pct": V2_ORB_PAPER_MAX_SPREAD_PCT,
        },
        "upstream_chain_liquidity_filtered": True,
    }
    try:
        from config.strategy_catalog import REVIEWED_STRATEGIES
        reviewed_tickers = set().union(*(
            rule.tickers
            for rule in REVIEWED_STRATEGIES.values()
            if not rule.observation_only
        ))
    except Exception:
        reviewed_tickers = {"TSLA"}
    if ticker not in reviewed_tickers:
        info["reason"] = "unsupported_v2_ticker"
        return None, info
    if direction not in {"bullish", "bearish"} or current_price <= 0 or max_spend <= 0:
        info["reason"] = "invalid_selection_input"
        return None, info

    option_type = "call" if direction == "bullish" else "put"
    try:
        expirations = tradier.get_expirations(ticker)
    except Exception as exc:
        logger.warning("V2 paper get_expirations(%s) raised: %s", ticker, exc)
        info["reason"] = "api_error"
        return None, info
    if not expirations:
        info["reason"] = "no_expirations"
        return None, info

    today = _now_et().date()
    candidates: list[tuple[int, float, float, str, dict]] = []
    saw_chain_data = False
    saw_budget_candidate = False
    saw_liquid_candidate = False
    for expiry in expirations:
        try:
            expiry_date = date.fromisoformat(str(expiry))
        except (TypeError, ValueError):
            continue
        dte = (expiry_date - today).days
        if not V2_ORB_PAPER_MIN_DTE <= dte <= V2_ORB_PAPER_MAX_DTE:
            continue
        try:
            chain = tradier.get_option_chain(ticker, str(expiry), option_type)
        except Exception as exc:
            logger.debug("V2 paper get_option_chain(%s) raised: %s", expiry, exc)
            continue
        if not chain:
            continue
        saw_chain_data = True
        for raw_contract in chain:
            contract = dict(raw_contract)
            try:
                strike = float(contract.get("strike") or 0)
                ask = float(contract.get("ask") or 0)
                bid = float(contract.get("bid") or 0)
            except (TypeError, ValueError):
                continue
            is_otm = strike > current_price if option_type == "call" else strike < current_price
            if not is_otm or not V2_ORB_PAPER_MIN_PREMIUM <= ask <= V2_ORB_PAPER_MAX_PREMIUM:
                continue
            cost = ask * 100
            if cost > max_spend:
                saw_budget_candidate = True
                continue
            mid = (ask + bid) / 2 if bid > 0 else 0.0
            spread_pct = (ask - bid) / mid if mid > 0 else float("inf")
            if spread_pct > V2_ORB_PAPER_MAX_SPREAD_PCT:
                saw_liquid_candidate = True
                continue
            symbol = str(contract.get("symbol") or "")
            if not symbol:
                continue
            contract["expiry"] = str(expiry)
            contract["selection_model"] = info["selection_model"]
            candidates.append((dte, abs(strike - current_price), spread_pct, symbol, contract))

    if not candidates:
        if saw_liquid_candidate:
            info["reason"] = "illiquid"
        elif saw_budget_candidate:
            info["reason"] = "over_budget"
        elif saw_chain_data:
            info["reason"] = "filtered"
        return None, info

    _, _, spread_pct, _, selected = min(candidates, key=lambda item: item[:4])
    info.update({
        "reason": "selected",
        "eligible_contract_count": len(candidates),
        "shadow_contract_leaderboard": _reviewed_contract_shadow_leaderboard(candidates),
        "selected_dte": (date.fromisoformat(selected["expiry"]) - today).days,
        "selected_spread_pct": round(spread_pct, 6),
    })
    (logger.debug if for_display else logger.info)(
        "Reviewed V2 contract selected: %s exp=%s strike=%.2f ask=%.2f model=%s",
        selected["symbol"], selected["expiry"], float(selected["strike"]),
        float(selected["ask"]), info["selection_model"],
    )
    return selected, info


# Existing callers retain the historic import name while new reviewed
# strategies use the neutral name above.
select_v2_orb_contract = select_reviewed_v2_contract

# Compatibility alias for callers from the original paper-validation rollout.
# New execution code uses select_v2_orb_contract so its behavior is not
# accidentally assumed to be paper-only.
select_v2_orb_paper_contract = select_reviewed_v2_contract
