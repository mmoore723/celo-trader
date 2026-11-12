"""
api/routes/signals.py — read-only endpoints over signal_journal.

Added 2026-07-24 per explicit user request: "we need to refactor bot
thinking... lets discuss how to make it useful." bot.log is an unstructured
50MB/day dump and ai_reasoning_log only narrates realized entries/exits —
neither answers "why didn't the bot trade today." signal_journal (see
signal_journal.py) records every strategy signal's final outcome, entered
or blocked-with-reason, and these three endpoints back the Thinking panel's
new summary bar, filterable row list, and 7-day trend strip.
"""

from __future__ import annotations

import logging
import json
from collections import Counter
from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException, Query

router = APIRouter(prefix="/api/signals", tags=["signals"])
logger = logging.getLogger("celo_trader.api.signals")


@router.get("/journal")
def get_journal(
    ticker: str | None = None,
    strategy: str | None = Query(None, description="Reviewed V2 strategy ID"),
    reason: str | None = Query(None, description="reason_code — see signal_journal.REASON_CODES"),
    limit: int = Query(200, ge=1, le=1000),
) -> dict:
    """Today's rows (ET calendar day), newest first, optionally filtered."""
    from signal_journal import get_todays_rows
    try:
        rows = get_todays_rows(ticker=ticker, strategy=strategy, reason=reason, limit=limit)
        return {"entries": rows, "count": len(rows)}
    except Exception as e:
        logger.exception("signal journal fetch failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/journal/summary")
def get_journal_summary() -> dict:
    """
    Today's breakdown: total signals, entered count, and a count per
    reason_code — backs the panel's top summary bar.
    """
    from signal_journal import get_todays_summary
    try:
        return get_todays_summary()
    except Exception as e:
        logger.exception("signal journal summary fetch failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/journal/trend")
def get_journal_trend(
    reason: str = Query(..., description="reason_code to trend — see signal_journal.REASON_CODES"),
    days: int = Query(7, ge=1, le=30),
) -> dict:
    """Daily count of one reason_code over the trailing N days."""
    from signal_journal import get_trend
    try:
        points = get_trend(reason_code=reason, days=days)
        return {"reason": reason, "days": days, "points": points}
    except Exception as e:
        logger.exception("signal journal trend fetch failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/journal/reasons")
def get_reason_codes() -> dict:
    """Reference list of reason codes + human-readable labels, for the filter dropdown."""
    from signal_journal import REASON_CODES
    return {"reasons": REASON_CODES}


def _json_object(value: object) -> dict:
    """Return an object from legacy/malformed JSON without breaking the audit UI."""
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        parsed = json.loads(str(value))
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}


def _setup_details(metadata: dict) -> dict[str, str | float | int | bool]:
    """Keep the learner-facing setup facts small, serializable, and useful.

    Strategy metadata is an internal audit object and can contain implementation
    tokens such as ``shadow_candidate_id``.  The Opportunities screen needs the
    human-relevant facts (opening-range high/low, VWAP, retest level, etc.), not
    an opaque JSON dump or an internal primary key.
    """
    hidden = {"shadow_candidate_id", "candidate_id", "ticker", "strategy_id"}
    # Keep the facts a person needs to recreate the chart setup at the front.
    # Strategy metadata is assembled in several places, so insertion order is
    # not a reliable definition of what matters most to a learner.
    priority = (
        "or_high", "or_low", "retest_level", "reference_945", "v2_entry_reference", "prior_high", "prior_low",
        "v2_stop", "v2_target", "vwap", "fast_ema", "slow_ema", "atr",
        "impulse_extreme", "pullback_low", "pullback_high", "reclaim_level", "entry_bar_low", "entry_bar_high",
        "entry_timing", "validated_entry_rule", "reviewed_paid_quote_rule", "entry_trigger",
    )
    result: dict[str, str | float | int | bool] = {}
    ordered_keys = [key for key in priority if key in metadata] + [
        key for key in metadata if key not in priority
    ]
    for key in ordered_keys:
        value = metadata[key]
        if key in hidden or value is None or isinstance(value, (dict, list, tuple)):
            continue
        if isinstance(value, (str, float, int, bool)):
            result[str(key)] = value
        if len(result) >= 16:
            break
    return result


def _plan_status(*, contract: dict, preview: dict | None = None, trade: dict | None, outcome: str) -> str:
    """Describe whether this record ever reached a real option selection."""
    preview = preview or {}
    if trade or contract.get("symbol") or contract.get("strike") is not None:
        return "contract_selected"
    if preview.get("symbol") or preview.get("strike") is not None:
        return "contract_preview"
    if outcome == "observed_only":
        return "observation_only"
    return "not_priced"


def _opportunity_lifecycle(entry: dict) -> str:
    """Return the plain-language stage shown consistently across the UI."""
    outcome = str(entry.get("outcome") or "pending")
    plan_status = str(entry.get("plan_status") or "not_priced")
    if outcome == "entered":
        return "entered"
    if outcome == "blocked":
        return "stopped"
    if outcome == "observed_only":
        return "research"
    if plan_status == "contract_selected":
        return "ready"
    if plan_status == "contract_preview":
        return "pricing"
    return "watching"


def _assign_opportunity_episodes(entries: list[dict]) -> list[list[dict]]:
    """Group repeated one-minute detections into independent setup episodes.

    A condition that remains true for five minutes is one developing setup,
    not five possible trades.  A new episode begins after fifteen quiet
    minutes or when ticker, strategy, direction, or trading day changes.
    """
    episodes: list[list[dict]] = []
    latest_by_identity: dict[tuple[str, str, str, str], list[dict]] = {}
    ordered = sorted(entries, key=lambda item: str(item.get("observed_at") or ""))
    for entry in ordered:
        when = _parse_audit_time(entry.get("observed_at"))
        identity = (
            str(entry.get("observed_at") or "")[:10], str(entry.get("ticker") or ""),
            str(entry.get("strategy_id") or ""), str(entry.get("direction") or ""),
        )
        current_episode = latest_by_identity.get(identity)
        prior = current_episode[-1] if current_episode else None
        prior_when = _parse_audit_time(prior.get("observed_at")) if prior else None
        if (not prior or not when or not prior_when
                or (when - prior_when).total_seconds() > 15 * 60):
            current_episode = [entry]
            latest_by_identity[identity] = current_episode
            episodes.append(current_episode)
        else:
            current_episode.append(entry)
    for index, episode in enumerate(episodes, start=1):
        first = episode[0]
        episode_id = "|".join((
            str(first.get("observed_at") or ""), str(first.get("ticker") or ""),
            str(first.get("strategy_id") or ""), str(first.get("direction") or ""),
        ))
        for occurrence, entry in enumerate(episode, start=1):
            entry["episode_id"] = episode_id
            entry["episode_occurrence"] = occurrence
            entry["episode_size"] = len(episode)
            entry["lifecycle"] = _opportunity_lifecycle(entry)
    return episodes


def _candidate_quote_timeline(rows: list[dict]) -> list[dict]:
    """Add conservative executable returns to a candidate's quote marks.

    Entry assumes buying at the recorded ask. Follow-up values assume selling
    at the recorded bid. This is a measured quote-to-quote result, not a fill.
    """
    entry = next((row for row in rows if row.get("observation_kind") == "entry"), None)
    entry_ask = float(entry.get("ask") or 0) if entry else 0.0
    timeline: list[dict] = []
    for row in rows:
        item = {
            key: row.get(key)
            for key in ("observation_kind", "observed_at", "contract_symbol", "bid", "ask", "mid", "last", "source")
        }
        exit_bid = float(row.get("bid") or 0)
        item["executable_return_pct"] = (
            round((exit_bid - entry_ask) / entry_ask * 100, 4)
            if row.get("observation_kind") != "entry" and entry_ask > 0 and exit_bid > 0
            else None
        )
        timeline.append(item)
    return timeline


def _fallback_contract_recipe(strategy_id: object, direction: object) -> dict[str, str | float]:
    """Describe the contract screen a learner should open when no quote was selected.

    Scanner Opportunities intentionally retains *every* candidate, including
    ones that never reached the entry router.  Those records cannot honestly
    claim a historical contract symbol or option quote.  They can still tell a
    person the exact contract-selection profile the bot would use if the
    setup became actionable.  A decision-time recipe in the journal always
    overrides this fallback.
    """
    from config.strategy_catalog import reviewed_strategy_ids
    reviewed_ids = reviewed_strategy_ids()
    reviewed = str(strategy_id or "").upper() in reviewed_ids
    option_type = "CALL" if str(direction or "").lower() in {"bullish", "long", "call"} else "PUT"
    return {
        "option_type": option_type,
        "strike_rule": "closest out-of-the-money strike to the underlying at selection",
        "premium_rule": "$0.80–$10.00 ask" if reviewed else "$0.05–$10.00 ask",
        "expiration_rule": "7–21 calendar days to expiration" if reviewed else "first broker-listed expiration with a qualifying contract",
        "spread_rule": "bid/ask spread no wider than 8% of mid",
        "liquidity_rule": "broker-returned liquid chain" if reviewed else "open interest of at least 100",
        "selection_model": "reviewed paid-quote profile" if reviewed else "standard liquid first-OTM profile",
        "recipe_source": "default_profile",
    }


def _contract_recipe(context: dict, strategy_id: object, direction: object) -> dict:
    recorded = context.get("contract_recipe") if isinstance(context.get("contract_recipe"), dict) else {}
    if recorded:
        return {**recorded, "recipe_source": "recorded"}
    return _fallback_contract_recipe(strategy_id, direction)


def _contract_preview(context: dict) -> dict:
    """Return a display-only option snapshot saved at signal time.

    This is distinct from ``contract``: the preview explains what the bot was
    looking at before a later gate stopped it.  It must never be confused with
    a selected contract, fill, or standing order.
    """
    preview = context.get("contract_preview") if isinstance(context, dict) else None
    return preview if isinstance(preview, dict) else {}


def _parse_audit_time(value: object) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _reconcile_legacy_journals(candidate_rows: list, orphan_journal: list[dict]) -> tuple[dict[str, dict], set[int]]:
    """Link pre-fix terminal decisions to their candidate without guessing broadly.

    Older router gates sometimes copied a Signal without its candidate ID.  The
    journal decision followed the candidate by only a few seconds.  Match only
    exact ticker/strategy/direction identities within 30 seconds, one-to-one.
    This repairs the read model without rewriting historical database rows.
    """
    matches: dict[str, dict] = {}
    used_journal_ids: set[int] = set()
    for raw_candidate in candidate_rows:
        candidate = dict(raw_candidate)
        if str(candidate.get("final_outcome") or "pending") != "pending":
            continue
        candidate_time = _parse_audit_time(candidate.get("observed_at"))
        if candidate_time is None:
            continue
        choices: list[tuple[float, dict]] = []
        for journal in orphan_journal:
            journal_id = int(journal.get("id") or 0)
            if journal_id in used_journal_ids or journal.get("outcome") not in {"blocked", "entered"}:
                continue
            if any(str(candidate.get(key) or "").lower() != str(journal.get(key) or "").lower()
                   for key in ("ticker", "strategy_id", "direction")):
                continue
            journal_time = _parse_audit_time(journal.get("ts"))
            if journal_time is None:
                continue
            seconds = abs((journal_time - candidate_time).total_seconds())
            if seconds <= 30:
                choices.append((seconds, journal))
        if choices:
            _, journal = min(choices, key=lambda item: item[0])
            matches[str(candidate.get("candidate_id"))] = journal
            used_journal_ids.add(int(journal.get("id") or 0))
    return matches, used_journal_ids


@router.get("/opportunities")
def get_scanner_opportunities(
    date: str | None = Query(None, description="ET calendar date, YYYY-MM-DD"),
    ticker: str | None = None,
    strategy: str | None = None,
    outcome: str | None = Query(None, description="pending | blocked | observed_only | entered"),
    feed: str | None = None,
    limit: int = Query(500, ge=1, le=1000),
) -> dict:
    """A day-by-day audit of every scanner candidate the router evaluated.

    This deliberately starts with ``shadow_candidates`` rather than the trade
    journal.  A trade journal can only show orders; this page must also retain
    the candidates the scanner saw but a gate stopped.  Contract, quantity,
    and exit-plan details are included only when the entry path actually
    reached those decisions.  No contract is invented for early gate rejects.
    """
    from config import get_settings
    from database import get_conn, _now_et

    selected_date = (date or _now_et().date().isoformat()).strip()
    # Keep the date input constrained to the stored ISO calendar shape.  This
    # also prevents passing a broad SQL pattern through this read-only filter.
    if len(selected_date) != 10 or selected_date[4] != "-" or selected_date[7] != "-":
        raise HTTPException(status_code=422, detail="date must use YYYY-MM-DD")

    account_id = get_settings().get("active_broker_account_id") or None
    clauses = ["sc.observed_at LIKE ?"]
    params: list[object] = [f"{selected_date}%"]
    if account_id:
        clauses.append("sc.broker_account_id = ?")
        params.append(account_id)
    else:
        # Keep legacy data separate too.  Falling back to every row here would
        # silently blend scanner history from different broker identities.
        clauses.append("(sc.broker_account_id IS NULL OR sc.broker_account_id = '')")
    if ticker:
        clauses.append("sc.ticker = ?")
        params.append(ticker.upper())
    if strategy:
        clauses.append("sc.strategy_id = ?")
        params.append(strategy)
    # Outcome is applied after legacy journal reconciliation below. Filtering
    # the candidate table here would hide old blocked decisions stored as
    # pending before the candidate-link preservation fix.

    where = " AND ".join(clauses)
    try:
        with get_conn() as conn:
            # A feed filter is applied after lifecycle reconciliation below.
            # Fetch the full bounded day first so a small client limit cannot
            # accidentally select four research rows and then display no
            # operational setups at all.
            query_limit = 1000 if feed else limit
            candidate_rows = conn.execute(
                "SELECT sc.*, t.ticker AS trade_ticker, t.contract_symbol, t.option_type, "
                "t.strike, t.expiry, t.contracts, t.entry_price, t.exit_price, t.stop_price, t.target_price, "
                "t.status AS trade_status, t.entry_time, t.exit_time, t.exit_reason, t.realized_pnl "
                "FROM shadow_candidates sc LEFT JOIN trades t ON t.id = sc.linked_trade_id "
                f"WHERE {where} ORDER BY sc.observed_at DESC LIMIT ?",
                tuple(params + [query_limit]),
            ).fetchall()
            quote_rows = conn.execute(
                "SELECT cq.* FROM candidate_option_quote_observations cq "
                "JOIN shadow_candidates sc ON sc.candidate_id = cq.candidate_id "
                "WHERE sc.observed_at LIKE ? "
                + ("AND sc.broker_account_id = ? " if account_id else "AND (sc.broker_account_id IS NULL OR sc.broker_account_id = '') ")
                + "ORDER BY cq.candidate_id, cq.id",
                (f"{selected_date}%", account_id) if account_id else (f"{selected_date}%",),
            ).fetchall()
            # The journal is the durable home for the enriched decision
            # context.  A candidate ID in strategy_meta is an explicit join,
            # never a fuzzy same-minute match that could join two setups.
            journal_where = ["ts LIKE ?"]
            journal_params: list[object] = [f"{selected_date}%"]
            if account_id:
                journal_where.append("broker_account_id = ?")
                journal_params.append(account_id)
            else:
                # A database created before account identities existed may
                # still have legacy rows.  Only surface those when there is
                # no active identity to protect, never alongside a new key.
                journal_where.append("(broker_account_id IS NULL OR broker_account_id = '')")
            journal_rows = conn.execute(
                "SELECT * FROM signal_journal WHERE " + " AND ".join(journal_where) + " ORDER BY id DESC",
                tuple(journal_params),
            ).fetchall()
            date_rows = conn.execute(
                "SELECT DISTINCT substr(observed_at, 1, 10) AS day FROM shadow_candidates "
                + ("WHERE broker_account_id = ? " if account_id else "WHERE (broker_account_id IS NULL OR broker_account_id = '') ")
                + "ORDER BY day DESC LIMIT 90",
                (account_id,) if account_id else (),
            ).fetchall()
    except Exception as exc:
        logger.exception("scanner opportunities query failed")
        raise HTTPException(status_code=500, detail=str(exc))

    from api.decision_explanation import explain_decision

    journal_by_candidate: dict[str, dict] = {}
    quotes_by_candidate: dict[str, list[dict]] = {}
    for raw in quote_rows:
        quote_row = dict(raw)
        quotes_by_candidate.setdefault(str(quote_row.get("candidate_id")), []).append(quote_row)
    orphan_journal: list[dict] = []
    for raw in journal_rows:
        row = dict(raw)
        context = _json_object(row.get("context_json"))
        meta = context.get("strategy_meta") if isinstance(context.get("strategy_meta"), dict) else {}
        candidate_id = meta.get("shadow_candidate_id")
        if candidate_id:
            journal_by_candidate.setdefault(str(candidate_id), {**row, "_context": context})
        else:
            orphan_journal.append({**row, "_context": context})

    legacy_matches, matched_orphan_ids = _reconcile_legacy_journals(candidate_rows, orphan_journal)
    for candidate_id, journal in legacy_matches.items():
        journal_by_candidate.setdefault(candidate_id, journal)

    entries: list[dict] = []
    for raw in candidate_rows:
        row = dict(raw)
        candidate_id = str(row["candidate_id"])
        journal = journal_by_candidate.get(candidate_id)
        context = journal.get("_context", {}) if journal else {}
        metadata = _json_object(row.get("metadata_json"))
        saved_plan = metadata.get("manual_plan") if isinstance(metadata.get("manual_plan"), dict) else {}
        # Final journal context wins when it exists; the candidate copy is the
        # durable fallback for a signal stopped before journaling.
        plan_context = {**saved_plan, **context}
        decision_meta = context.get("strategy_meta") if isinstance(context.get("strategy_meta"), dict) else {}
        # Decision-time context is preferred because it contains the selected
        # contract if entry evaluation reached it.  Raw metadata remains the
        # fallback for observed-only candidates.
        contract = plan_context.get("contract") if isinstance(plan_context.get("contract"), dict) else {}
        contract_recipe = _contract_recipe(plan_context, row.get("strategy_id"), row.get("direction"))
        contract_selection = plan_context.get("contract_selection") if isinstance(plan_context.get("contract_selection"), dict) else {}
        contract_preview = _contract_preview(plan_context)
        quote_timeline = _candidate_quote_timeline(quotes_by_candidate.get(candidate_id, []))
        entry_plan = plan_context.get("entry_plan") if isinstance(plan_context.get("entry_plan"), dict) else {}
        exit_plan = plan_context.get("exit_plan") if isinstance(plan_context.get("exit_plan"), dict) else {}
        order_intent = plan_context.get("order_intent") if isinstance(plan_context.get("order_intent"), dict) else {}
        if not entry_plan:
            entry_plan = {"trigger": metadata.get("entry_trigger") or "Scanner setup detected"}
        stored_outcome = str(row.get("final_outcome") or "pending")
        outcome_value = str(journal.get("outcome") or stored_outcome) if journal else stored_outcome
        reason_code = row.get("gate_reason") or (journal.get("reason_code") if journal else None)
        reason_detail = row.get("gate_detail") or (journal.get("reason_detail") if journal else None)
        screen = decision_meta.get("premarket_screen") or metadata.get("premarket_screen") or {}
        decision_source = "recorded decision"
        # Read-only recovery from the decision-time snapshot, never current settings.
        # Do not overwrite entered, research-only or independently blocked outcomes.
        if (outcome_value == "pending" and not reason_code and not reason_detail
                and isinstance(screen, dict) and screen.get("allowed") is False):
            outcome_value = "blocked"
            reason_code = "premarket_screen_rejected"
            decision_source = "saved premarket check; final journal entry was missing"
        explanation = explain_decision(row, plan_context, {**metadata, **decision_meta},
                                       reason_code, reason_detail, decision_source)
        trade = None
        if row.get("linked_trade_id"):
            trade = {
                "id": row.get("linked_trade_id"), "contract_symbol": row.get("contract_symbol"),
                "option_type": row.get("option_type"), "strike": row.get("strike"),
                "expiry": row.get("expiry"), "contracts": row.get("contracts"),
                "entry_price": row.get("entry_price"), "exit_price": row.get("exit_price"),
                "stop_price": row.get("stop_price"), "target_price": row.get("target_price"),
                "status": row.get("trade_status"), "entry_time": row.get("entry_time"),
                "exit_time": row.get("exit_time"), "exit_reason": row.get("exit_reason"),
                "pnl": row.get("realized_pnl"),
            }
        entries.append({
            "id": candidate_id, "source": "candidate", "observed_at": row.get("observed_at"),
            "ticker": row.get("ticker"), "strategy_id": row.get("strategy_id"),
            "direction": row.get("direction"), "confidence": row.get("confidence"),
            "tier": row.get("tier"), "trigger_bar": row.get("trigger_bar"),
            "outcome": outcome_value, "reason_code": reason_code, "reason_detail": reason_detail,
            "entry_plan": entry_plan, "contract": contract, "contract_preview": contract_preview,
            "contract_recipe": contract_recipe, "contract_selection": contract_selection,
            "planned_quantity": plan_context.get("planned_quantity"), "exit_plan": exit_plan,
            "order_intent": order_intent, "explanation": explanation,
            "plan_status": _plan_status(contract=contract, preview=contract_preview, trade=trade, outcome=outcome_value),
            "option_quote_timeline": quote_timeline,
            "option_type": (trade or {}).get("option_type") or (
                "call" if str(row.get("direction") or "").lower() in {"bullish", "long", "call"} else "put"
            ),
            # A raw candidate contains the setup as first observed.  Once it
            # reaches the entry path, that path may add precise facts such as
            # the actual retouch level.  Merge both audit snapshots so the
            # learner sees the complete recorded plan—not a reconstructed one.
            "setup_details": _setup_details({**metadata, **decision_meta}),
            "underlying_entry_price": row.get("underlying_entry_price"),
            "underlying_exit_price": row.get("underlying_exit_price"),
            "directional_move_pct": row.get("directional_move_pct"),
            "direction_correct": row.get("direction_correct"),
            "outcome_observed_at": row.get("outcome_observed_at"), "trade": trade,
        })

    # Pre-link historical journal rows are still worth displaying.  Clearly
    # label them as journal-only: they do not have a candidate outcome or a
    # virtual fill behind them, so a learner will not mistake them for one.
    candidate_ids_in_page = {str(dict(row)["candidate_id"]) for row in candidate_rows}
    for journal in orphan_journal:
        if int(journal.get("id") or 0) in matched_orphan_ids:
            continue
        context = journal.get("_context", {})
        meta = context.get("strategy_meta") if isinstance(context.get("strategy_meta"), dict) else {}
        if str(meta.get("shadow_candidate_id") or "") in candidate_ids_in_page:
            continue
        if ticker and journal.get("ticker") != ticker.upper():
            continue
        if strategy and journal.get("strategy_id") != strategy:
            continue
        if outcome and journal.get("outcome") != outcome:
            continue
        entries.append({
            "id": f"journal-{journal.get('id')}", "source": "journal_only", "observed_at": journal.get("ts"),
            "ticker": journal.get("ticker"), "strategy_id": journal.get("strategy_id"),
            "direction": journal.get("direction"), "confidence": journal.get("confidence"),
            "tier": journal.get("tier") or "main", "trigger_bar": context.get("trigger_bar"),
            "outcome": journal.get("outcome"), "reason_code": journal.get("reason_code"),
            "reason_detail": journal.get("reason_detail"),
            "explanation": explain_decision(journal, context, meta, journal.get("reason_code"),
                                             journal.get("reason_detail"), "recorded decision"),
            "entry_plan": context.get("entry_plan") if isinstance(context.get("entry_plan"), dict) else {},
            "contract": context.get("contract") if isinstance(context.get("contract"), dict) else {},
            "contract_preview": _contract_preview(context),
            "contract_recipe": _contract_recipe(context, journal.get("strategy_id"), journal.get("direction")),
            "contract_selection": context.get("contract_selection") if isinstance(context.get("contract_selection"), dict) else {},
            "planned_quantity": context.get("planned_quantity"),
            "exit_plan": context.get("exit_plan") if isinstance(context.get("exit_plan"), dict) else {},
            "order_intent": context.get("order_intent") if isinstance(context.get("order_intent"), dict) else {},
            "plan_status": _plan_status(
                contract=context.get("contract") if isinstance(context.get("contract"), dict) else {},
                preview=_contract_preview(context),
                trade={"id": journal.get("trade_id")} if journal.get("trade_id") else None,
                outcome=str(journal.get("outcome") or "pending"),
            ),
            "option_quote_timeline": [],
            "option_type": (
                "call" if str(journal.get("direction") or "").lower() in {"bullish", "long", "call"} else "put"
            ),
            "setup_details": _setup_details(meta),
            "underlying_entry_price": None, "underlying_exit_price": None,
            "directional_move_pct": None, "direction_correct": None,
            "outcome_observed_at": None,
            "trade": {"id": journal.get("trade_id")} if journal.get("trade_id") else None,
        })
    # Add lifecycle/episode metadata before sorting for display. This prevents
    # five consecutive observations of one condition from being presented as
    # five independent trade opportunities.
    episodes = _assign_opportunity_episodes(entries)
    entries.sort(key=lambda entry: str(entry.get("observed_at") or ""), reverse=True)
    if outcome:
        entries = [entry for entry in entries if entry.get("outcome") == outcome]
    if feed == "operational":
        entries = [entry for entry in entries if entry.get("lifecycle") != "research"]
    elif feed == "research":
        entries = [entry for entry in entries if entry.get("lifecycle") == "research"]
    elif feed is not None:
        raise HTTPException(status_code=422, detail="feed must be operational or research")
    entries = entries[:limit]

    # Summary cards count independent episodes, not raw one-minute rows. Use
    # the furthest stage reached by any observation within that episode.
    lifecycle_rank = {"research": 0, "watching": 1, "pricing": 2, "ready": 3, "stopped": 4, "entered": 5}
    episode_stages: list[str] = []
    visible_ids = {str(entry.get("id")) for entry in entries}
    for episode in episodes:
        visible_episode = [entry for entry in episode if str(entry.get("id")) in visible_ids]
        if not visible_episode:
            continue
        stage = max(
            (str(entry.get("lifecycle") or "watching") for entry in visible_episode),
            key=lambda value: lifecycle_rank.get(value, -1),
        )
        episode_stages.append(stage)
    stage_counts = Counter(episode_stages)
    entered = stage_counts.get("entered", 0)
    blocked = stage_counts.get("stopped", 0)
    research_only = stage_counts.get("research", 0)
    watching = stage_counts.get("watching", 0)
    pricing = stage_counts.get("pricing", 0)
    ready = stage_counts.get("ready", 0)
    return {
        "date": selected_date, "account_scoped": bool(account_id),
        "available_dates": [str(row["day"]) for row in date_rows if row["day"]],
        "summary": {
            "setups": len(episode_stages), "raw_detections": len(entries),
            "actionable": entered + blocked + pricing + ready,
            "entered": entered, "stopped": blocked, "research": research_only,
            "watching": watching, "pricing": pricing, "ready": ready,
            # Transitional aliases for older clients and saved tests. These
            # retain their historical names while using the corrected episode
            # semantics rather than raw one-minute detection counts.
            "total": len(episode_stages), "blocked": blocked,
            "observed": research_only, "routed": entered + blocked,
            "unresolved": watching + pricing + ready,
        },
        "note": "Setups count independent episodes; raw detections count repeated scanner checks. Watching means the pattern is incomplete. Pricing means contract checks began. Ready means a contract was selected but no entry record exists. Stopped always includes the recorded reason. Entered always links to the actual trade.",
        "entries": entries,
    }


@router.get("/gate-scorecard")
def get_gate_scorecard(days: int = Query(30, ge=1, le=365)) -> dict:
    """Counterfactual evidence for decision gates, grouped by strategy.

    A veto is helpful when the rejected setup later loses and harmful when it
    later wins.  Prefer the recorded option ask-to-60-minute-bid return; use
    the underlying directional grade only when an option quote was not yet
    captured.  This endpoint is read-only and never promotes a gate.
    """
    from config import get_settings
    from database import get_conn, _now_et

    account_id = get_settings().get("active_broker_account_id") or None
    cutoff = (_now_et() - timedelta(days=days)).isoformat()
    account_candidate = "broker_account_id = ?" if account_id else "(broker_account_id IS NULL OR broker_account_id = '')"
    account_journal = account_candidate
    params = (cutoff, account_id) if account_id else (cutoff,)
    try:
        with get_conn() as conn:
            candidates = conn.execute(
                "SELECT * FROM shadow_candidates WHERE observed_at >= ? AND " + account_candidate,
                params,
            ).fetchall()
            ai_rows = conn.execute(
                "SELECT * FROM ai_reasoning_log WHERE event_type='entry_veto' AND ts >= ? ORDER BY ts",
                (cutoff,),
            ).fetchall()
            journals = conn.execute(
                "SELECT * FROM signal_journal WHERE ts >= ? AND " + account_journal,
                params,
            ).fetchall()
            quote_rows = conn.execute(
                "SELECT q.* FROM candidate_option_quote_observations q "
                "JOIN shadow_candidates sc ON sc.candidate_id=q.candidate_id "
                "WHERE sc.observed_at >= ? AND " + ("sc.broker_account_id = ?" if account_id else "(sc.broker_account_id IS NULL OR sc.broker_account_id = '')"),
                params,
            ).fetchall()
    except Exception as exc:
        logger.exception("gate scorecard query failed")
        raise HTTPException(status_code=500, detail=str(exc))

    explicit: dict[str, dict] = {}
    orphan: list[dict] = []
    for raw in journals:
        journal = dict(raw)
        context = _json_object(journal.get("context_json"))
        meta = context.get("strategy_meta") if isinstance(context.get("strategy_meta"), dict) else {}
        candidate_id = meta.get("shadow_candidate_id")
        if candidate_id:
            explicit.setdefault(str(candidate_id), journal)
        else:
            orphan.append(journal)
    legacy, _ = _reconcile_legacy_journals(candidates, orphan)
    explicit.update({key: value for key, value in legacy.items() if key not in explicit})

    quotes: dict[str, dict[str, dict]] = {}
    for raw in quote_rows:
        quote = dict(raw)
        quotes.setdefault(str(quote.get("candidate_id")), {})[str(quote.get("observation_kind"))] = quote

    candidate_dicts = [dict(row) for row in candidates]
    ai_by_candidate: dict[str, dict] = {}
    used_ai_candidates: set[str] = set()
    for raw in ai_rows:
        ai_row = dict(raw)
        if ai_row.get("error"):
            continue  # fail-open is availability evidence, not model skill
        snapshot = _json_object(ai_row.get("feature_snapshot_json"))
        action = str(snapshot.get("decision_action") or "")
        if not action:
            response = str(ai_row.get("response_text") or "")
            for chunk in response.split("|"):
                if chunk.strip().upper().startswith("ACTION:"):
                    action = chunk.partition(":")[2].strip().lower()
                    break
        if action not in {"approve", "veto", "reduce_size"}:
            continue
        candidate_id = str(snapshot.get("candidate_id") or "")
        if not candidate_id:
            ai_time = _parse_audit_time(ai_row.get("ts"))
            choices: list[tuple[float, str]] = []
            for candidate in candidate_dicts:
                cid = str(candidate.get("candidate_id"))
                if cid in used_ai_candidates:
                    continue
                if any(str(candidate.get(key) or "").lower() != str(snapshot.get(key) or ai_row.get(key) or "").lower()
                       for key in ("ticker", "strategy_id", "direction")):
                    continue
                candidate_time = _parse_audit_time(candidate.get("observed_at"))
                if ai_time and candidate_time:
                    seconds = abs((ai_time - candidate_time).total_seconds())
                    if seconds <= 60:
                        choices.append((seconds, cid))
            if choices:
                _, candidate_id = min(choices, key=lambda item: item[0])
        if candidate_id:
            try:
                multiplier = max(0.0, min(float(snapshot.get("decision_size_multiplier", 1.0)), 1.0))
            except (TypeError, ValueError):
                multiplier = 1.0
            ai_by_candidate[candidate_id] = {"action": action, "size_multiplier": multiplier}
            used_ai_candidates.add(candidate_id)

    def measured_result(candidate_id: str, candidate: dict) -> tuple[bool | None, float | None, bool]:
        entry_quote = quotes.get(candidate_id, {}).get("entry")
        exit_quote = quotes.get(candidate_id, {}).get("mark_60m")
        if entry_quote and exit_quote:
            entry_ask = float(entry_quote.get("ask") or 0)
            exit_bid = float(exit_quote.get("bid") or 0)
            if entry_ask > 0 and exit_bid > 0:
                option_return = (exit_bid - entry_ask) / entry_ask * 100
                return option_return > 0, option_return, True
        if candidate.get("direction_correct") is not None:
            return bool(candidate.get("direction_correct")), None, False
        return None, None, False

    # One strategy condition can remain true for many consecutive one-minute
    # ticks. Those rows are repeated observations of ONE setup, not separate
    # trades. Score the first actionable decision in each episode (a new
    # episode begins after 15 quiet minutes) so the AI cannot look more
    # certain merely because it repeated itself. If it vetoes first and
    # approves later in the same episode, report that as a delay too.
    evaluated: dict[str, list[dict]] = {}
    for candidate in candidate_dicts:
        candidate_id = str(candidate.get("candidate_id"))
        journal = explicit.get(candidate_id)
        reason = str(candidate.get("gate_reason") or (journal or {}).get("reason_code") or "")
        ai_decision = ai_by_candidate.get(candidate_id)
        action = ai_decision.get("action") if ai_decision else None
        gate = "ai_decision_veto" if action else reason
        if gate not in {"ai_decision_veto", "macro_vwap_veto"}:
            continue
        record = dict(candidate)
        record["_gate"] = gate
        record["_action"] = action or "veto"
        record["_size_multiplier"] = ai_decision.get("size_multiplier", 1.0) if ai_decision else 0.0
        evaluated.setdefault(gate, []).append(record)

    grouped: dict[tuple[str, str], dict] = {}
    for gate, gate_records in evaluated.items():
        gate_records.sort(key=lambda row: str(row.get("observed_at") or ""))
        episodes: list[list[dict]] = []
        for record in gate_records:
            when = _parse_audit_time(record.get("observed_at"))
            identity = (
                str(record.get("observed_at") or "")[:10],
                str(record.get("ticker") or ""),
                str(record.get("strategy_id") or ""),
                str(record.get("direction") or ""),
            )
            prior = episodes[-1][-1] if episodes else None
            prior_when = _parse_audit_time(prior.get("observed_at")) if prior else None
            prior_identity = (
                str(prior.get("observed_at") or "")[:10], str(prior.get("ticker") or ""),
                str(prior.get("strategy_id") or ""), str(prior.get("direction") or ""),
            ) if prior else None
            if (not prior or identity != prior_identity or not when or not prior_when
                    or (when - prior_when).total_seconds() > 15 * 60):
                episodes.append([record])
            else:
                episodes[-1].append(record)

        for episode in episodes:
            first = episode[0]
            key = (str(first.get("strategy_id")), gate)
            item = grouped.setdefault(key, {
                "strategy_id": key[0], "gate": gate,
                "raw_decisions": 0, "independent_episodes": 0,
                "vetoes": 0, "measured": 0, "avoided_losers": 0,
                "rejected_winners": 0, "option_measured": 0,
                "delayed_then_allowed": 0, "option_return_parts": [],
                "policy_episodes": [],
                "trading_days": set(),
                "allowed": {"decisions": 0, "measured": 0, "winners": 0,
                            "losers": 0, "option_measured": 0},
            })
            item["raw_decisions"] += len(episode)
            item["independent_episodes"] += 1
            item["trading_days"].add(str(first.get("observed_at") or "")[:10])
            first_action = str(first.get("_action") or "veto")
            candidate_id = str(first.get("candidate_id"))
            winner, option_return, option_used = measured_result(candidate_id, first)
            if gate == "ai_decision_veto" and option_used and option_return is not None:
                multiplier = float(first.get("_size_multiplier") or 0.0)
                policy_return = 0.0 if first_action == "veto" else float(option_return) * multiplier
                item["policy_episodes"].append({
                    "observed_at": first.get("observed_at"), "action": first_action,
                    "baseline_return_pct": float(option_return),
                    "policy_return_pct": policy_return,
                })
            if first_action == "veto":
                item["vetoes"] += 1
                if any(str(row.get("_action")) in {"approve", "reduce_size"} for row in episode[1:]):
                    item["delayed_then_allowed"] += 1
                if option_used:
                    item["option_measured"] += 1
                    item["option_return_parts"].append(option_return)
                if winner is not None:
                    item["measured"] += 1
                    item["rejected_winners" if winner else "avoided_losers"] += 1
            else:
                allowed = item["allowed"]
                allowed["decisions"] += 1
                if winner is not None:
                    allowed["measured"] += 1
                    allowed["winners" if winner else "losers"] += 1
                    if option_used:
                        allowed["option_measured"] += 1

    rows: list[dict] = []
    from ai_reasoning.gate_policy import ai_decision_is_enforced
    from ai_reasoning.calibration import evaluate_ai_gate_policy
    for item in grouped.values():
        measured = int(item["measured"])
        option_parts = item.pop("option_return_parts")
        item["trading_days"] = len(item["trading_days"])
        item["avoided_loser_rate_pct"] = round(item["avoided_losers"] / measured * 100, 1) if measured else None
        item["rejected_winner_rate_pct"] = round(item["rejected_winners"] / measured * 100, 1) if measured else None
        item["avg_rejected_option_return_pct"] = round(sum(option_parts) / len(option_parts), 3) if option_parts else None
        allowed = item["allowed"]
        allowed["win_rate_pct"] = round(allowed["winners"] / allowed["measured"] * 100, 1) if allowed["measured"] else None
        policy_episodes = item.pop("policy_episodes")
        validation = evaluate_ai_gate_policy(policy_episodes) if item["gate"] == "ai_decision_veto" else None
        item["validation"] = validation
        item["status"] = validation["status"] if validation else "descriptive_only"
        item["enforced"] = bool(
            item["gate"] != "ai_decision_veto" or ai_decision_is_enforced(item["strategy_id"])
        )
        item["minimum_evidence"] = validation["minimum_evidence"] if validation else {}
        rows.append(item)
    return {
        "days": days, "account_scoped": bool(account_id),
        "policy": "An unproven AI opinion is recorded but cannot change a trade. It becomes enforceable for one strategy only after enough independent option outcomes and a later-date holdout comparison against that same strategy with the AI ignored.",
        "rows": sorted(rows, key=lambda row: (row["strategy_id"], row["gate"])),
    }


def resolve_watching_contracts(watched: list[dict]) -> list[dict]:
    """
    Given watched entries (ticker, direction, or_boundary, phase,
    breakout_bar, retest_bar), resolve each one's real contract — strike,
    expiration, live bid/ask — via select_contract(), the SAME function
    trading/entry.py calls for a real entry, so this shows what would
    actually be bought right now, not a guess.

    Shared by /api/signals/watching and /api/tickers/board (see
    api/routes/tickers.py) so both surfaces resolve the identical contract
    for the identical ticker from one implementation — two copies of this
    logic is exactly the kind of drift that caused the earlier IEX-volume
    bug (see market_data.py's docstring), just in a new place.
    """
    if not watched:
        return []
    from broker import get_clients
    from trading.entry import select_contract
    from config import get_settings

    alpaca, tradier = get_clients()
    settings = get_settings()

    try:
        acct = alpaca.get_account()
        balance = float(acct.get("equity", 0)) if acct else 0.0
    except Exception:
        balance = 0.0
    if balance <= 0:
        balance = float(settings.get("last_known_balance", 0) or 0)

    cap_pct = settings.get("max_position_dollars_pct")
    if cap_pct:
        max_spend = balance * (float(cap_pct) / 100.0)
    else:
        max_spend = float(settings.get("max_position_dollars", 750.0))

    out = []
    for w in watched:
        ticker    = w["ticker"]
        direction = w.get("direction")

        current_price = 0.0
        try:
            quote = alpaca.get_latest_quote(ticker)
            if quote:
                current_price = (float(quote.get("ap", 0) or 0) + float(quote.get("bp", 0) or 0)) / 2
        except Exception:
            pass

        contract = None
        if current_price > 0 and direction and max_spend > 0:
            try:
                # for_display=True — this is a price refresh for the watching
                # card, not a real entry attempt. See select_contract()'s
                # docstring for the incident this prevents.
                contract, _info = select_contract(tradier, ticker, direction, current_price, max_spend, for_display=True)
            except Exception as ex:
                logger.debug("resolve_watching_contracts: select_contract failed for %s: %s", ticker, ex)

        out.append({
            **w,
            "current_price": current_price or None,
            "contract": {
                "symbol": contract.get("symbol"),
                "strike": contract.get("strike"),
                "expiry": contract.get("expiry"),
                "bid":    contract.get("bid"),
                "ask":    contract.get("ask"),
            } if contract else None,
        })
    return out


@router.get("/watching")
def get_watching() -> dict:
    """Legacy compatibility endpoint; rebuilt strategies have no hidden wait state."""
    return {"watching": []}
