"""Independent price/arithmetic and account verification for the fixed TSLA test.

Does not rerun signal selection or assert these studied dates are a holdout.
All missing results remain explicit; account totals are invalidated as complete
evidence if an arm omits entries or needs an unresolved emergency exit.
"""
import argparse
from collections import Counter
import contextlib
import csv
from datetime import datetime, timedelta
from decimal import Decimal as D
import hashlib
import io
import json
import os
from pathlib import Path
import re

from research.jobs.replay_account_controls import replay

SID = "V2_TSLA_TWO_LEG_TREND_PULLBACK"


def at(value):
    stamp = datetime.fromisoformat(value)
    if stamp.tzinfo is None or stamp.second or stamp.microsecond:
        raise ValueError("Expected aware minute timestamp")
    return stamp


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def metrics(values):
    wins = sum((v for v in values if v>0), D(0))
    losses = -sum((v for v in values if v<0), D(0))
    return dict(results=len(values), wins=sum(v>0 for v in values), net=float(sum(values,D(0))),
                pf=float(wins/losses) if losses else None)


def validate(data, baseline):
    if data.get("protocol") != "two_leg_affordable_fixed142_original90m_v1" or not data.get("complete"):
        raise ValueError("Wrong or incomplete experiment")
    original = [r for r in baseline["rows"] if r["status"] == "priced"]
    if (data["coverage"] != dict(Counter(r["status"] for r in baseline["rows"])) or
            [r["date"] for r in data["rows"]] != [r["date"] for r in original] or
            set(data["member_sha256"]) != {r["date"] for r in original}):
        raise ValueError("Coverage/cohort changed")
    for row, old in zip(data["rows"], original):
        start, end = at(old["entry_time"]), at(old["exit_time"])
        if (row["strategy_id"] != SID or row["ticker"] != "TSLA" or at(row["entry_time"]) != start or
                row["direction"] != old["direction"] or row["stock_reference"] != old["stock_reference"] or
                end-start != timedelta(minutes=91)):
            raise ValueError("Original decision identity changed")
        if any(set(row[k]) != {"control", "candidate"} for k in ("selections", "paths", "outcomes")):
            raise ValueError("Missing comparison arm")
        for name in ("control", "candidate"):
            first, path, outcome = row["selections"][name], row["paths"][name], row["outcomes"][name]
            if at(outcome["exit_time"]) != end:
                raise ValueError("Exit clock changed")
            if first is None:
                if name == "control" or path or outcome["status"] != "no_affordable_contract" or "net" in outcome:
                    raise ValueError("Missing contract hidden")
                continue
            symbol = re.fullmatch(r"TSLA\s+(\d{6})([CP])(\d{8})", first["contract"])
            if symbol is None:
                raise ValueError("Wrong option contract")
            expiry = datetime.strptime(symbol[1], "%y%m%d").date()
            strike, spot = D(symbol[3])/1000, D(str(old["stock_reference"]))
            bullish = old["direction"] == "bullish"
            ask, bid = D(first["ask"]), D(first["bid"])
            ceiling = D(10) if name == "control" else D("1.42")
            if (not 7 <= (expiry-start.date()).days <= 21 or symbol[2] != ("C" if bullish else "P") or
                    not (strike>spot if bullish else strike<spot) or not D(".80")<=ask<=ceiling or
                    (ask-bid)/((ask+bid)/2)>D(".08")):
                raise ValueError("Contract profile changed")
            times = [at(q["time"]) for q in path]
            if not times or times != sorted(set(times)) or times[0] != start or path[0] != first:
                raise ValueError("Entry/path missing or duplicated")
            for q in path:
                numbers = [D(q[k]) for k in ("ask","bid","ask_size","bid_size")]
                if (not all(v.is_finite() and v>0 for v in numbers) or numbers[1]>numbers[0] or
                        not start<=at(q["time"])<=end or q["contract"] != first["contract"]):
                    raise ValueError("Invalid or cross-contract quote path")
            if name == "control" and (first["contract"] != old["contract"].strip() or
                    ask != D(str(old["entry_ask"])) or bid != D(str(old["entry_bid"]))):
                raise ValueError("Control entry price changed")
            last = next((q for q in path if at(q["time"]) == end), None)
            if last is None:
                if name == "control" or outcome["status"] != "missing_exit" or "net" in outcome:
                    raise ValueError("Missing exit hidden")
                continue
            net = (D(last["bid"])-ask)*100-D("3.30")
            if outcome["status"] != "priced" or D(outcome["exit_bid"]) != D(last["bid"]) or D(outcome["net"]) != net:
                raise ValueError("Exit price/cost mismatch")
            if name == "control" and abs(net-D(str(old["net_pnl_one_contract"])))>D(".000002"):
                raise ValueError("Control net changed")


def analyze(data, settings, sessions):
    summary, accounts = {}, {}
    for name in ("control", "candidate"):
        values = [D(r["outcomes"][name]["net"]) for r in data["rows"] if r["outcomes"][name]["status"] == "priced"]
        summary[name] = dict(metrics(values), statuses=dict(Counter(r["outcomes"][name]["status"] for r in data["rows"])))
        trades, quotes, gaps = [], [], []
        for row in data["rows"]:
            first, outcome, path = row["selections"][name], row["outcomes"][name], row["paths"][name]
            if outcome["status"] != "priced":
                continue
            if any((at(b["time"])-at(a["time"])).total_seconds()>120 for a,b in zip(path,path[1:])):
                gaps.append(row["date"])
            trades.append(dict(id=row["date"],ticker="TSLA",strategy_id=SID,contracts=1,contract_symbol=first["contract"],
                entry_time=row["entry_time"],exit_time=outcome["exit_time"],entry_price=first["ask"],entry_bid=first["bid"],
                entry_size=first["ask_size"],exit_price=outcome["exit_bid"]))
            quotes.extend(dict(trade_id=row["date"],observed_at=q["time"],bid=q["bid"]) for q in path)
        for stress in (0,.01,.05):
            with contextlib.redirect_stdout(io.StringIO()):
                result = replay(trades,quotes,settings,fee_per_side=1.65,friction_per_side=stress,
                    settlement_sessions=sessions,ticker_routing=True,routing_paper=settings["paper_trading"])
            result["priced_entries"] = len(trades)
            result["original_entries"] = len(data["rows"])
            result["quote_paths_with_gaps_over_120s"] = gaps
            result["skip_counts"] = dict(Counter(d["reason"] for d in result["decisions"] if d["action"] == "skip"))
            source = {r["date"]:r for r in data["rows"]}
            result["insufficient_exit_depth"] = [r["id"] for r in result["closed"]
                if D(source[r["id"]]["paths"][name][-1]["bid_size"])<r["quantity"]]
            result["account_replay_has_unresolved_evidence"] = bool(
                summary[name]["statuses"].get("missing_exit",0) or gaps or
                result["insufficient_exit_depth"] or result["unresolved_emergency_exits"])
            if abs(sum(D(str(r["pnl"])) for r in result["closed"])-D(str(result["net_pnl"])))>D(".000001"):
                raise ValueError("Account P&L does not reconcile")
            accounts[f"{name}_{stress}"] = result
    pairs = [(D(r["outcomes"]["control"]["net"]),D(r["outcomes"]["candidate"]["net"]))
             for r in data["rows"] if r["outcomes"]["candidate"]["status"] == "priced"]
    effects = dict(paired=len(pairs), lost_winners=sum(a>0 and b<=0 for a,b in pairs),
        change_on_original_winners=float(sum((b-a for a,b in pairs if a>0),D(0))),
        change_on_original_losers=float(sum((b-a for a,b in pairs if a<0),D(0))),
        paired_control=metrics([a for a,b in pairs]),paired_candidate=metrics([b for a,b in pairs]))
    return dict(summary=summary,winner_effects=effects,accounts=accounts)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ("input","baseline","settings","bars","output"):
        parser.add_argument("--"+name,type=Path,required=True)
    args=parser.parse_args()
    data=json.loads(args.input.read_text()); baseline=json.loads(args.baseline.read_text())
    if data["baseline_sha256"]!=sha(args.baseline) or data["bars_sha256"]!=sha(args.bars):
        raise ValueError("Source fingerprint changed")
    for name, fingerprint in data["code_sha256"].items():
        if sha(Path(__file__).with_name(name))!=fingerprint:
            raise ValueError("Producer/helper changed")
    validate(data,baseline)
    verified=json.loads(args.settings.read_text())
    if verified.get("all_checks_pass") is not True:
        raise ValueError("Settings source not verified")
    with args.bars.open() as source:
        reader=csv.DictReader(source)
        field="timestamp" if "timestamp" in reader.fieldnames else "time"
        sessions=sorted({r[field][:10] for r in reader})
    result=dict(protocol="two_leg_affordable_independent_verification_v1",coverage=data["coverage"],
        sources={str(p):sha(p) for p in (args.input,args.baseline,args.settings,args.bars,Path(__file__),
            Path(__file__).with_name("replay_account_controls.py"))},
        **analyze(data,verified["risk_settings"],sessions),
        limitations=["119 retained native setups; 14 incomplete mornings remain untested",
            "Already-studied history, not untouched holdout or future profit proof",
            "Sampled minute bids and instantaneous fills; gaps/depth failures remain disclosed",
            "Fixed initial ask cap, not contract reselection as account equity changes",
            "Single TSLA strategy, not all-six portfolio; other scheduler gates not replayed"])
    fd=os.open(args.output,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,"w") as out:
        json.dump(result,out,indent=2,allow_nan=False)
    print(json.dumps({k:result[k] for k in ("summary","winner_effects")},indent=2))
    print(json.dumps({name:{k:r[k] for k in ("ending_equity","pf","sampled_drawdown","longest_losing_streak",
        "skip_counts","quote_paths_with_gaps_over_120s","insufficient_exit_depth","unresolved_emergency_exits")}
        for name,r in result["accounts"].items()},indent=2))


if __name__=="__main__":
    main()
