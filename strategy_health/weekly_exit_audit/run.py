"""Offline weekly audit worker. Never run a search inside a UI request."""
import argparse
import fcntl
import json
import re

from .engine import audit
from .source import load
from .store import save


def run(user):
    if not re.fullmatch(r"[A-Za-z0-9_-]+", user) or user == "system":
        raise ValueError("Explicit valid tenant required")
    from auth.context import set_current_user
    from config.paths import get_user_data_dir
    set_current_user(user, user, False)
    directory = get_user_data_dir(create=False)
    if not directory.is_dir():
        raise ValueError("User data directory does not exist")
    with (directory/"weekly_exit_audit.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        for mode in ("paper", "live"):
            buckets = load(directory/f"trades_{mode}.db", mode)
            for key, trades in buckets.items():
                try:
                    result = audit(trades)
                except (ValueError, TypeError, KeyError, ArithmeticError) as exc:
                    result = dict(status="INCOMPLETE", recommendation="KEEP BASELINE",
                                  reason=f"Invalid source evidence: {type(exc).__name__}",
                                  trade_count=len(trades), assumptions=[])
                audit_id = save(directory/"weekly_exit_audits.sqlite3", key, result, trades)
                print(json.dumps(dict(id=audit_id, mode=mode, ticker=key[2], strategy=key[3],
                                      version=key[4], status=result["status"],
                                      recommendation=result["recommendation"])), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--user", required=True)
    run(parser.parse_args().user)
