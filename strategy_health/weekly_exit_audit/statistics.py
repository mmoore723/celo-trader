"""Paired, multiplicity-adjusted audit statistics."""
from statistics import NormalDist
import numpy as np


def metrics(values):
    a = np.asarray(values, dtype=float)
    if not len(a) or not np.isfinite(a).all():
        return None
    gains, losses = a[a > 0].sum(), -a[a < 0].sum()
    equity = np.r_[0., a.cumsum()]
    return dict(trades=len(a), net=round(float(a.sum()), 2),
                win_rate=round(100*float((a > 0).mean()), 2),
                profit_factor=float(gains/losses) if losses else None,
                profit_factor_infinite=bool(gains > 0 and losses == 0),
                max_drawdown=round(float((np.maximum.accumulate(equity)-equity).max()), 2),
                worst_trade=round(float(a.min()), 2))


def qualifies(result):
    return bool(result and result["max_drawdown"] < 1200
                and (result["profit_factor_infinite"]
                     or (result["profit_factor"] or 0) > 1.5))


def noise(candidate, baseline, combinations=939):
    """Normal-approximation Bonferroni bound with positive-lag HAC inflation."""
    differences = np.asarray(candidate)-np.asarray(baseline)
    n = len(differences)
    if n < 2:
        return dict(available=False, exceeds_noise=False, reason="Fewer than two paired trades")
    centered = differences-differences.mean()
    variance = float(centered @ centered/(n-1))
    lags = min(5, n-1)
    for lag in range(1, lags+1):
        covariance = float(centered[lag:] @ centered[:-lag]/n)
        variance += 2*(1-lag/(lags+1))*max(0., covariance)
    standard_error = (variance/n)**.5
    critical = NormalDist().inv_cdf(1-.05/combinations)
    threshold = critical*standard_error*n
    improvement = float(differences.sum())
    return dict(available=True, trades=n, combinations=combinations,
                combinations_per_trade=round(combinations/n, 3),
                pnl_difference_standard_error=standard_error,
                total_noise_threshold=threshold, improvement=improvement,
                exceeds_noise=bool(improvement > threshold),
                method="One-sided5% Bonferroni normal approximation; paired P&L differences; positive-lag HAC, up to5 lags.")
