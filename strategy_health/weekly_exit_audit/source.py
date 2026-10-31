"""Read-only audit journal adapter. Never migrate or write a trading database."""
import json
import sqlite3
import math
from collections import defaultdict
from datetime import timedelta

from .replay import clock, enrich


def journal_time(value):
    from database.helpers import _to_et_datetime
    return _to_et_datetime(value).isoformat()


def recorded_hold(context, meta, strategy):
    hold = context.get("max_hold_minutes") or context.get("reviewed_exit_minutes")
    if hold:
        return hold
    plan = (meta.get("manual_plan") or {}).get("exit_plan") or {}
    if (plan.get("strategy_id") == strategy and
            plan.get("summary") == "Hold the same selected contract for 30 minutes, then exit at the executable bid."):
        return 30
    return None


def parsed(value):
    try:
        result = json.loads(value or "{}")
        return result if isinstance(result, dict) else {}
    except (ValueError, TypeError):
        return {}


def recorded_version(context, meta):
    """Keep economic strategy version separate from a corrected runtime."""
    versions = {v for v in (context.get('strategy_version'), meta.get('strategy_version')) if v}
    revisions = {v for v in (context.get('runtime_revision'), meta.get('runtime_revision')) if v}
    if len(versions) != 1 or len(revisions) > 1:
        return None
    version = next(iter(versions))
    return version + '+runtime.' + next(iter(revisions)) if revisions else version


def load(path, mode):
    if mode not in ("paper", "live"):
        raise ValueError("Invalid account mode")
    if not path.exists():
        return {}
    conn = sqlite3.connect(path.as_uri()+"?mode=ro", uri=True, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    conn.execute("BEGIN")
    underlying_paths = {}
    try:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "trades" not in tables:
            return {}
        trades = [dict(r) for r in conn.execute("SELECT * FROM trades WHERE paper=? ORDER BY entry_time,id", (mode == "paper",))]
        candidates = {}
        if "shadow_candidates" in tables:
            candidates = {(r["candidate_id"], r["broker_account_id"], r["strategy_id"], r["ticker"]):
                          parsed(r["metadata_json"]) for r in conn.execute("""
                SELECT DISTINCT s.candidate_id,s.broker_account_id,s.strategy_id,s.ticker,s.metadata_json
                FROM trades t JOIN shadow_candidates s ON s.candidate_id=t.candidate_id
                AND s.broker_account_id=t.broker_account_id AND s.strategy_id=t.strategy_id AND s.ticker=t.ticker
                WHERE t.paper=?""", (mode == "paper",))}
        quotes = defaultdict(list)
        if "option_quote_observations" in tables:
            for r in conn.execute("""SELECT q.trade_id,q.contract_symbol,q.observed_at,q.bid,q.ask
                FROM trades t JOIN option_quote_observations q ON q.trade_id=t.id
                WHERE t.paper=? ORDER BY q.trade_id,q.observed_at,q.id""", (mode == "paper",)):
                try:
                    stamp = journal_time(r["observed_at"])
                except (ValueError, TypeError, AttributeError):
                    stamp = r["observed_at"]
                quotes[r["trade_id"]].append(dict(time=stamp, bid=r["bid"], ask=r["ask"],
                                                  contract=r["contract_symbol"]))
        if 'scanner_candle_observations' in tables:
            from .underlying import load_path
            for row in trades:
                if row['status'] != 'closed':
                    continue
                context=parsed(row.get('strategy_context_json'))
                meta=candidates.get((row.get('candidate_id'),row.get('broker_account_id'),row['strategy_id'],row['ticker']),{})
                horizon=context.get('exit_deadline')
                hold=recorded_hold(context,meta,row['strategy_id'])
                if not horizon and hold:
                    try:
                        horizon=(clock(journal_time(row['entry_time']))+timedelta(minutes=float(hold))).isoformat()
                    except (ValueError,TypeError,OverflowError):
                        pass
                horizon=horizon or row.get('exit_fill_time') or row.get('exit_time')
                underlying_paths[row['id']]=load_path(conn,row,horizon)
    finally:
        conn.close()
    positions = defaultdict(list)
    for trade in trades:
        account = trade.get("broker_account_id")
        raw_meta = candidates.get((trade.get("candidate_id"), account, trade["strategy_id"], trade["ticker"]), {})
        raw_context = parsed(trade.get("strategy_context_json"))
        frozen_versions = frozenset([recorded_version(raw_context, raw_meta)])
        positions[(account, trade["ticker"], trade["strategy_id"], frozen_versions,
                   trade.get("parent_trade_id") or trade["id"])].append(trade)
    buckets = defaultdict(list)
    for (account, _ticker, _strategy, _versions, root), legs in positions.items():
        if any(t["status"] != "closed" for t in legs):
            continue
        first = next((t for t in legs if t["id"] == root), legs[0])
        context = parsed(first.get("strategy_context_json"))
        meta = candidates.get((first.get("candidate_id"), account, first["strategy_id"], first["ticker"]), {})
        versions = set()
        for leg in legs:
            leg_context = parsed(leg.get("strategy_context_json"))
            leg_meta = candidates.get((leg.get("candidate_id"), account, leg["strategy_id"], leg["ticker"]), {})
            versions.add(recorded_version(leg_context, leg_meta))
        version = next(iter(versions)) if len(versions) == 1 and None not in versions else f"UNKNOWN-TRADE-{root}"
        issues = []
        if len(versions) != 1 or None in versions:
            issues.append("unknown_or_conflicting_version")
        if not account:
            issues.append("unknown_broker_account")
        if len(legs) > 1:
            issues.append("partial_position_requires_reconstruction")
        if first["id"] != root:
            issues.append("missing_parent")
        observed = [q for q in quotes[first["id"]] if q["contract"] == first["contract_symbol"]
                    and q["bid"] is not None and q["ask"] is not None]
        entry_time = first.get("entry_fill_time") or first["entry_time"]
        exit_time = first.get("exit_fill_time") or first["exit_time"]
        try:
            entry_time = journal_time(entry_time)
            exit_time = journal_time(exit_time)
        except (ValueError, TypeError, AttributeError):
            issues.append("invalid_journal_timestamp")
        deadline = context.get("exit_deadline")
        hold = recorded_hold(context, meta, first["strategy_id"])
        if not deadline and hold:
            try:
                deadline = (clock(journal_time(first["entry_time"]))+timedelta(minutes=float(hold))).isoformat()
            except (ValueError, TypeError, OverflowError):
                issues.append("invalid_deadline")
        quantity = int(first["contracts"])
        trade = dict(id=root, entry_time=entry_time,
                     exit_time=exit_time,
                     entry_price=float(first["entry_price"]), quantity=quantity,
                     contract=first["contract_symbol"], realized_pnl=None,
                     entry_iv=context.get("entry_iv"), entry_delta=context.get("entry_delta"),
                     entry_gamma=context.get("entry_gamma"), underlying_path=context.get("underlying_1m_path"),
                     deadline=deadline, fees=context.get("roundtrip_fees", 3.30*quantity),
                     fees_assumed="roundtrip_fees" not in context, option_path=observed, issues=issues)
        stored_path, path_info = underlying_paths.get(first['id'], (None, {'status':'no_scanner_candle_table'}))
        if not trade['underlying_path']:
            trade['underlying_path']=stored_path
            trade['underlying_path_evidence']=path_info
        snapshot=context.get('entry_greeks_snapshot')
        if isinstance(snapshot,dict):
            trade['entry_greeks_evidence']=snapshot
            try:
                if (snapshot.get('contract_symbol')!=first['contract_symbol']
                        or snapshot.get('source_symbol')!=first['contract_symbol']
                        or snapshot.get('source')!='tradier'
                        or clock(snapshot['received_at'])>clock(entry_time)):
                    raise ValueError('greeks_not_available_at_entry')
                if snapshot.get('model_timestamp_verified', True):
                    if clock(snapshot['provider_updated_at'])>clock(snapshot['received_at']):
                        raise ValueError('future_model_timestamp')
            except (ValueError,TypeError,KeyError):
                for field in ('entry_iv','entry_delta','entry_gamma'):
                    trade[field]=None
                trade['entry_greeks_validation']='unverified_entry_snapshot'
        try:
            pnl = sum(float(t["realized_pnl"]) for t in legs)
            if not math.isfinite(pnl):
                raise ValueError("Non-finite P&L")
            trade["realized_pnl"] = pnl
        except (TypeError, ValueError):
            trade["issues"].append("missing_realized_pnl")
        try:
            trade = enrich(trade)
        except (ValueError, TypeError, OverflowError):
            trade["issues"].append("invalid_price_or_timezone")
        key = (account or f"UNKNOWN-TRADE-{root}", mode, first["ticker"], first["strategy_id"], version)
        buckets[key].append(trade)
    return dict(buckets)
