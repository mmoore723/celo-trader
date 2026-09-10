# Reviewed timed exits: September 10, 2026 audit

Five current strategies already measure their authored exit through the shared
candidate option quote collector. They do not require another structural-exit
row: ORB Pullback and TSLA Two-Leg hold 90 minutes; SPY Trend Continuation,
SPY Afternoon FVG, and Failed-Range Recovery hold 30 minutes. These values
match the current catalog and `evaluate_v2_orb_paper_exit`. All 26 current
strategies therefore have a measurement path: 21 separate structural/premium
collectors plus these five timed exits. Coverage is not proof of profitability.

The collector incorrectly scheduled both primary and alternative contracts
from the scanner signal timestamp. The matrix judges elapsed time from the
priced entry. A delayed entry could therefore create an early mark that the
matrix correctly rejects. Collection now starts from each contract's own
entry timestamp, with Eastern-time normalization for aware and stored naive
timestamps. The existing five-minute late window stays unchanged. Missing
windows are not backfilled. No historical records or trading rules change.

The exit label also now verifies that the requested horizon equals the
catalog's native hold. Other horizons remain comparisons, not the strategy's
actual exit. Tests cover both native horizons, all five IDs, delayed entries,
independent alternative timing, duplicate sweeps, account isolation, missed
windows, after-cost arithmetic, and the absence of broker trades.

Read-only production checks of observations since September 5 found delayed
entries, but no early native marks in the inspected recent sample. This fix
addresses a reproducible measurement defect, not a demonstrated explanation
for recent trading losses. Shared marks use sampled quotes and a five-minute
window, not guaranteed broker fills. Dynamic-exit profitability still requires
causal same-contract quotes, realistic costs, and untouched later test dates.
