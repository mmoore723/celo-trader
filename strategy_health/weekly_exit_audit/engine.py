"""Accumulated-history exit audit. Recommendations cannot execute orders."""
from itertools import product

from .replay import clock, replay
from .statistics import metrics, noise, qualifies

ASSUMPTIONS = [
    "Each bucket is one account, paper/live mode, ticker, strategy and frozen entry-time code version.",
    "Unknown or conflicting versions are not assigned the current catalog version.",
    "Recorded strategy-version labels cannot prove that historical deployments never changed behavior without a version bump.",
    "All available closed trades are considered, not only the latest week. Open positions are excluded.",
    "Same contracts, entries and quantities. Earlier exits do not create new entries.",
    "Activation is gross option profit per contract; giveback is a strict crossing, evaluated once per minute.",
    "Next valid recorded bid1..121 seconds after decision is assumed executable; no queue, depth, partial-fill, impact or measured network-latency model.",
    "Quote gaps over121 seconds or missing counterfactual future quotes invalidate that replay; no carried-forward synthetic fills.",
    "Recorded explicit round-trip fees are used; otherwise $3.30 per contract is assumed and labeled.",
    "Frozen recorded exit deadline is required; no universal strategy holding limit is invented.",
    "MFE/MAE are observed bid excursions during the actual holding period, not tick-complete extrema.",
    "IV, delta, gamma and underlying candles are supplemental for this dollar-giveback/time-only audit. Missing values disable dependent analyses, not this search. COMPLETE applies only to the reported audit scope.",
    "Recorded realized P&L and hypothetical65/35 baseline are distinct and shown separately.",
    "Drawdown uses cumulative closed-trade P&L from zero, not intratrade or account equity; no sizing or account-level risk simulation.",
    "Profit factor is gross positive net outcomes divided by absolute negative net outcomes; no-loss samples are explicitly infinite.",
    "70% training count is rounded down. Parameters are selected on training net only within training constraints; ties favor lower activation then giveback.",
    "One chronological split is not multiple walk-forward folds or proof of a pristine holdout after earlier research.",
    "Noise uses paired return standard error, positive-lag HAC and a one-sided Bonferroni normal approximation across939 predeclared configurations.",
    "Normality, stationarity and short-range dependence may fail. The correction does not cover earlier campaigns.",
    "If grid evidence is unconvincing, only predeclared30/60/90-minute time-only exits are explored; the stored deadline caps them. No volatility/anchor result is fabricated.",
    "A proposal requires complete bucket coverage, at least30 training and20 test trades, qualifying train/test metrics, and positive multiplicity-adjusted improvement in both segments.",
    "KEEP BASELINE with incomplete data means insufficient evidence to propose a change, not proof the currently deployed exit is optimal or safe.",
]


def audit(trades):
    problems = {}
    supplemental = {}
    required = ("entry_iv", "entry_delta", "entry_gamma", "underlying_path")
    for trade in trades:
        optional_missing = [key for key in required if trade.get(key) is None or trade.get(key) == []]
        if optional_missing:
            supplemental[str(trade['id'])] = optional_missing
        missing = []
        if trade.get("issues"):
            missing += trade["issues"]
        if not trade.get("deadline"):
            missing.append("frozen_exit_deadline")
        try:
            clock(trade["entry_time"])
        except (ValueError, TypeError):
            missing.append("invalid_entry_timestamp_or_missing_timezone")
        if missing:
            problems[str(trade["id"])] = missing
    result = dict(recommendation="KEEP BASELINE", status="INCOMPLETE",
                  trade_count=len(trades), coverage_issues=problems,
                  actual_recorded=metrics([t["realized_pnl"] for t in trades if t.get("realized_pnl") is not None]),
                  baseline=None, top10=[], walk_forward=None, noise=None,
                  alternatives=[], assumptions=ASSUMPTIONS, grid_combinations=936)
    result.update(audit_scope='option_dollar_giveback_and_time_barriers',
                  completion_meaning='Replay coverage only, not sufficient evidence to tune exits.',
                  sample_evidence=dict(train_count=int(len(trades)*.7),
                      test_count=len(trades)-int(len(trades)*.7),
                      minimum_train=30, minimum_test=20,
                      sufficient=int(len(trades)*.7) >= 30 and len(trades)-int(len(trades)*.7) >= 20),
                  supplemental_coverage_issues=supplemental,
                  supplemental_inputs_complete=not supplemental,
                  untested_exit_families=['iv_scaled_activation', 'underlying_structural_exits'])
    if not trades or any(not t.get("deadline") or t.get("issues") or
                         "invalid_entry_timestamp_or_missing_timezone" in problems.get(str(t["id"]), [])
                         for t in trades):
        result["reason"] = "Replay requires complete positions, known versions and frozen exit deadlines."
        return result
    trades = sorted(trades, key=lambda t: clock(t["entry_time"]))
    configs = list(product(range(25, 151, 5), range(15, 51)))
    returns, rows, failures = {}, [], {}
    for activation, tolerance in configs:
        outputs = [replay(t, activation, tolerance) for t in trades]
        missing = {str(t["id"]): o["status"] for t, o in zip(trades, outputs) if o["status"] != "priced"}
        key = f"{activation}/{tolerance}"
        if missing:
            failures[key] = missing
            continue
        values = [o["net"] for o in outputs]
        returns[key] = values
        rows.append(dict(setting=key, activation=activation, giveback=tolerance, **metrics(values)))
    result["grid"] = rows
    result["incomplete_configurations"] = failures
    if "65/35" not in returns:
        result["reason"] = "Recorded quote paths cannot reproduce the hypothetical65/35 baseline for every trade."
        return result
    base = returns["65/35"]
    result["baseline"] = metrics(base)
    leaders = sorted([r for r in rows if qualifies(r)], key=lambda r: (-r["net"], r["activation"], r["giveback"]))
    result["top10"] = leaders[:10]
    if leaders:
        result["noise"] = noise(returns[leaders[0]["setting"]], base)
    cut = int(len(trades)*.7)
    eligible = [r for r in rows if qualifies(metrics(returns[r["setting"]][:cut]))]
    eligible.sort(key=lambda r: (-sum(returns[r["setting"]][:cut]), r["activation"], r["giveback"]))
    if eligible and cut and cut < len(trades):
        winner = eligible[0]["setting"]
        values = returns[winner]
        train_noise, test_noise = noise(values[:cut], base[:cut]), noise(values[cut:], base[cut:])
        result["walk_forward"] = dict(setting=winner, train_count=cut, test_count=len(trades)-cut,
            train=metrics(values[:cut]), test=metrics(values[cut:]),
            baseline_train=metrics(base[:cut]), baseline_test=metrics(base[cut:]),
            train_noise=train_noise, test_noise=test_noise,
            holds_out_of_sample=bool(test_noise["exceeds_noise"] and qualifies(metrics(values[cut:]))))
        if (not problems and not failures and cut >= 30 and len(trades)-cut >= 20
                and train_noise["exceeds_noise"] and test_noise["exceeds_noise"]
                and qualifies(metrics(values[cut:]))):
            result["recommendation"] = "PROPOSE CHANGE"
            result["proposed_setting"] = winner
    if result["recommendation"] == "KEEP BASELINE":
        for minutes in (30, 60, 90):
            outputs = [replay(t, time_barrier=minutes) for t in trades]
            if all(o["status"] == "priced" for o in outputs):
                values = [o["net"] for o in outputs]
                result["alternatives"].append(dict(setting=f"time_only_{minutes}m",
                    **metrics(values), noise=noise(values, base),
                    train=metrics(values[:cut]), test=metrics(values[cut:])))
            else:
                result["alternatives"].append(dict(setting=f"time_only_{minutes}m", status="INCOMPLETE"))
    result["status"] = "COMPLETE" if not problems and not failures else "INCOMPLETE"
    result["reason"] = ("Manual approval required; no automatic application."
                        if result["recommendation"] == "PROPOSE CHANGE"
                        else "No fully validated improvement meeting all coverage, noise and chronological-test requirements.")
    if not result['sample_evidence']['sufficient']:
        result['reason'] = (
            f"{len(trades)} trades: {cut} training / {len(trades)-cut} test. "
            "Insufficient evidence to select better parameters; at least 30 training and 20 test trades required. "
            "COMPLETE means replay coverage only. Keep baseline.")
    return result
