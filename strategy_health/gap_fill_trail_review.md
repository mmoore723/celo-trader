# Gap Fill exit review — September 10, 2026

Source checked: `research/engine/strategies/gap_fill_rth.py`, the shared
`Simulator`, and `research/jobs/run_gap_fill_rth.py`. The job sets the 15:55
five-minute bar as session exit, observable at 16:00. The simulator defaults
to 75 managed bars, five-basis-point reference entry slip, and an untouched
entry candle. Its fixed target is a placeholder, not an exit.

Gap Fill uses the same short-trail defect documented in
[the ten-source trail audit](momentum_trail_review.md). Those ten primary
sources were reviewed before applying the same correction here. Short stops
should follow the lowest underlying price, not its highest. No ATR smoothing,
period, multiplier, entry gate, re-arming rule, or threshold is tuned here.

## Frozen paired test

New Gap Fill candidates record their own source fingerprint and last 15
completed five-minute bars. The original protocol repeats the original
simulator, including its short anchor. A separate bearish-only protocol uses
the lowest price instead. Both use identical candidates, entry ask/time and
contract, the original 14-bar simple ATR/2x trail, initial stop, session/hold
limits and next-bar tightening. Completed one-minute stop touches timestamp
the decision; fresh same-contract bids price the option afterward.

Only doubly priced, identity-matched candidates enter the after-cost paired
comparison. Never mix Gap Fill and Opening Momentum protocols or fingerprints.
Never relabel prior timer tests or historical fills. No research cooldown,
broker orders, paper/live rule changes or automatic promotion are added.

The original SPY underlying study lost on both its fitting and later dates;
fixing this bug alone does not establish a profitable strategy. Collect
prospective results, compare mean/median improvement, PF, drawdown and missing
price coverage, then judge later-date stability before any promotion request.
