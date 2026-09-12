"""Frozen TSLA Two-Leg affordability experiment, not production trading.

Keep all 251 baseline session classifications, the 119 native entry clocks,
OTM side, first three 7-21 DTE expiries, 8% spread ceiling and 90-minute exit.
Candidate only caps the ask at $1.42, derived from the unchanged $5k account
risk budget including its 5% entry reserve. No threshold sweep. Every original
ranked contract, entry quote and exit bid must reproduce or the job stops.
Costs are $3.30 roundtrip per contract, matching the baseline convention.
Retain both minute quote paths, including displayed sizes, for account replay.
Stream retained compressed ZIP members without extracting or downloading data.
These dates have already been studied and are NOT an untouched holdout.
"""
import argparse
from collections import Counter
from datetime import timedelta
from decimal import Decimal as D
import hashlib
import json
from pathlib import Path
import re
import shutil
from zipfile import ZipFile

from research.jobs.replay_displacement_affordable import HashedReader, csv_groups, identity
from research.jobs.replay_spy_affordable_contracts import checkpoint, digest, moment, quote

PROTOCOL = "two_leg_affordable_fixed142_original90m_v1"
SID = "V2_TSLA_TWO_LEG_TREND_PULLBACK"


def choose(entry, rows, now):
    if entry["direction"] not in ("bullish", "bearish"):
        raise ValueError("Unknown direction")
    parsed = [(r, identity(r["symbol"], "TSLA")) for r in rows]
    expiries = sorted({p[0] for _, p in parsed if p and 7 <= (p[0]-now.date()).days <= 21})[:3]
    bullish = entry["direction"] == "bullish"
    spot = D(str(entry["stock_reference"]))
    pools = {"control": {}, "candidate": {}}
    for raw, p in parsed:
        if not p or p[0] not in expiries or p[1] != ("C" if bullish else "P"):
            continue
        if not (p[2] > spot if bullish else p[2] < spot):
            continue
        q = quote(raw, now)
        if q is None:
            continue
        ask, bid = D(q["ask"]), D(q["bid"])
        spread = (ask-bid)/((ask+bid)/2)
        if spread > D(".08"):
            continue
        key = (p[0], abs(p[2]-spot), spread, q["contract"])
        for name, ceiling in (("control", D(10)), ("candidate", D("1.42"))):
            if D(".80") <= ask <= ceiling:
                previous = pools[name].get(q["contract"])
                if previous and previous != (key, q):
                    raise ValueError("Conflicting entry quote")
                pools[name][q["contract"]] = key, q
    return {name: min(pool.values(), key=lambda pair: pair[0])[1] if pool else None
            for name, pool in pools.items()}


def price(entry, groups):
    start, end = moment(entry["entry_time"]), moment(entry["exit_time"])
    if end-start != timedelta(minutes=91):
        raise ValueError("Original exit must be first snapshot after the 90-minute decision")
    picks, paths = None, {"control": [], "candidate": []}
    for now, group in groups:
        if now < start or now > end:
            continue
        if now == start:
            picks = choose(entry, group.to_dict("records"), now)
        wanted = {q["contract"] for q in (picks or {}).values() if q}
        book = {}
        for raw in group[group["symbol"].str.strip().isin(wanted)].to_dict("records"):
            q = quote(raw, now)
            if q:
                if q["contract"] in book and book[q["contract"]] != q:
                    raise ValueError("Conflicting path quote")
                book[q["contract"]] = q
        for name, q in (picks or {}).items():
            if q and q["contract"] in book:
                paths[name].append(book[q["contract"]])
    if picks is None or picks["control"] is None:
        raise ValueError("Original entry snapshot or first-three-expiry contract absent")
    first = picks["control"]
    if first["contract"] != entry["contract"].strip() or any(
            D(first[k]) != D(str(entry["entry_"+k])) for k in ("ask", "bid")):
        raise ValueError("Original ranked contract or entry quote differs")
    outcomes = {}
    for name, first in picks.items():
        last = next((q for q in paths[name] if moment(q["time"]) == end), None)
        outcome = dict(status="no_affordable_contract" if first is None else "missing_exit",
                       exit_time=end.isoformat())
        if first and last:
            net = (D(last["bid"])-D(first["ask"]))*100-D("3.30")
            outcome.update(status="priced", exit_bid=last["bid"], net=str(net))
        if name == "control" and (outcome["status"] != "priced" or
                D(outcome["exit_bid"]) != D(str(entry["exit_bid"])) or
                abs(D(outcome["net"])-D(str(entry["net_pnl_one_contract"]))) > D(".000002")):
            raise ValueError("Original exit or costs differ")
        outcomes[name] = outcome
    return dict(date=entry["date"], strategy_id=SID, ticker="TSLA", direction=entry["direction"],
                stock_reference=entry["stock_reference"], entry_time=start.isoformat(),
                selections=picks, paths=paths, outcomes=outcomes)


def validate_baseline(baseline):
    if (baseline.get("protocol") != "two_leg_causal_prefix_snapshot_clock_baseline_v2" or
            baseline.get("quote_clock_policy") != "cbbo_interval_end_ts_recv_v2" or
            not baseline.get("complete")):
        raise ValueError("Wrong or incomplete baseline")
    dates = [r["date"] for r in baseline["rows"]]
    coverage = dict(Counter(r["status"] for r in baseline["rows"]))
    if (len(dates) != baseline["sessions"] or dates != sorted(set(dates)) or
            dates != [r["date"] for r in baseline["manifest"]] or
            coverage != {"priced": 119, "no_setup": 118, "incomplete_morning": 14}):
        raise ValueError("Frozen session coverage changed")
    return coverage


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("baseline", "archive", "archive-proof", "bars", "output"):
        parser.add_argument("--"+name, type=Path, required=True)
    parser.add_argument("--resume", action="store_true", help="Only after verifying the prior job has terminated")
    args = parser.parse_args()
    if args.output.exists() and not args.resume:
        raise ValueError("Output exists; verify prior process before explicit resume")
    baseline = json.loads(args.baseline.read_text())
    coverage = validate_baseline(baseline)
    archive_proof = json.loads(args.archive_proof.read_text())
    if str(args.archive.resolve()) != baseline["archive"] or str(args.archive.resolve()) != archive_proof["archive"]:
        raise ValueError("Wrong retained archive")
    if digest(args.archive) != archive_proof["archive_sha256"] or digest(args.bars) != baseline["bars_sha256"]:
        raise ValueError("Archive or underlying bars changed")
    root = Path(__file__).resolve().parents[2]
    for name in ("trading/two_leg_trend_pullback_execution.py", "strategies/price_action_context.py"):
        if digest(root/name) != baseline["code_hashes"][name]:
            raise ValueError("Native entry implementation changed")
    code = (Path(__file__), Path(__file__).with_name("replay_displacement_affordable.py"),
            Path(__file__).with_name("replay_spy_affordable_contracts.py"))
    fixed = dict(protocol=PROTOCOL, baseline_sha256=digest(args.baseline),
        archive_sha256=archive_proof["archive_sha256"], archive_proof_sha256=digest(args.archive_proof),
        bars_sha256=baseline["bars_sha256"], code_sha256={p.name: digest(p) for p in code},
        coverage=coverage, maximum_ask="1.42", costs_per_roundtrip="3.30")
    result = json.loads(args.output.read_text()) if args.output.exists() else dict(
        **fixed, complete=False, rows=[], member_sha256={})
    if any(result.get(k) != v for k, v in fixed.items()):
        raise ValueError("Checkpoint identity changed")
    entries = [r for r in baseline["rows"] if r["status"] == "priced"]
    if [r["date"] for r in result["rows"]] != [r["date"] for r in entries[:len(result["rows"])]]:
        raise ValueError("Checkpoint cohort changed")
    with ZipFile(args.archive) as archive:
        meta = json.loads(archive.read("metadata.json"))["query"]
        if meta["schema"] != "cbbo-1m" or meta["symbols"] != ["TSLA.OPT"] or meta["encoding"] != "csv":
            raise ValueError("Wrong source metadata")
        infos = sorted((i for i in archive.infolist() if re.search(r'-\d{8}\.cbbo-1m\.(?:csv|dbn)(?:\.zst)?$', i.filename)), key=lambda i: i.filename)
        manifest = hashlib.sha256(json.dumps([(i.filename, i.CRC, i.file_size) for i in infos]).encode()).hexdigest()
        if manifest != baseline["archive_manifest_sha256"]:
            raise ValueError("Archive manifest changed")
        members = {r["date"]: r["member"] for r in baseline["manifest"]}
        checkpoint(args.output, result)
        for entry in entries[len(result["rows"]):]:
            if shutil.disk_usage(args.output.parent).free < 2*1024**3:
                raise ValueError("Disk reserve reached")
            with archive.open(members[entry["date"]]) as raw:
                source = HashedReader(raw)
                row = price(entry, csv_groups(source))
                member_hash = source.digest.hexdigest()
            result["rows"].append(row)
            result["member_sha256"][entry["date"]] = member_hash
            result["complete"] = len(result["rows"]) == len(entries)
            checkpoint(args.output, result)
            print(f'{len(result["rows"])}/{len(entries)} {entry["date"]}: {row["outcomes"]["candidate"]["status"]}', flush=True)


if __name__ == "__main__":
    main()
