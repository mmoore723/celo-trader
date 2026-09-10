# VWAP KER exit measurement — September 10, 2026

No locked strategy code, entry rules, user settings or order route changes.
Reference: /Applications/celo_trader/research/engine/context_option_replay.py,
structural_exit_for_signal, _session_vwaps and option_path_outcome. The entry
source is strategies/context_strategy_observers.py and remains hash-locked.

The saved exit is the first later one-minute high reaching the signal's
previous_high, or a completed five-minute close below contemporaneous session
VWAP. VWAP uses five-minute high/low/close typical price and summed volume,
with max(volume,1) weights matching the saved replay. It is not entry VWAP.
Equal-time target and stop retain the replay's target-first tie. Option P&L
still uses an actual bid: reaching the stock target does not guarantee profit.
The original replay's explicit 15:55 ET fallback is retained; it was a test
assumption, not a suggestion-specified time stop. Early-close support remains
an unresolved calendar limitation, not a claim of complete calendar coverage.

Entry quotes must arrive during the entry minute. The entry minute's high is
excluded because it could precede the purchase; subsequent completed minutes
can trigger the target, and the next five-minute close can trigger VWAP exit.
That conservative timing difference from the legacy replay is explicit.
Missing session candles/volume cannot produce a fabricated VWAP or result.
Recent missing bars get five minutes to arrive; unavailable data then becomes
unmeasurable. Structural decisions need the same-contract option bid within
one minute, including network latency, matching the saved quote replay window.
First decisions persist through retries. All overlapping research plays are
measured with shared quote fetches, without portfolio allocation limits.

New records only: version/proof/protocol remain distinct from timer evidence.
Costs use the application's .01-per-side slippage and .65-per-side contract
fee. Genuine KER entry/cross-ticker tests, completed-bar timing, session VWAP,
missing inputs, real quote loss arithmetic, restart and account isolation
are covered. Existing ORB premium paths are separately regression-tested.
No PF improvement or live promotion claimed.

## Displacement v0.2.0 registration — September 10, 2026

Reviewed artifact config/strategy_evidence/ctx_vwap_displacement-0.2.0.json
and trading/vwap_displacement_exit.py confirm the same structural plan.
The new protocol stamps both the unchanged entry module and execution-exit
module hashes. KER records/proof remain backward-compatible; each strategy
and current version has separate results. Genuine META observation uses the
actual candles through the existing alias/scope adapter, never order routing.

With complete candles, parity tests cover prior-high target, five-minute VWAP
stop and 15:55 cap against the actual execution evaluator. Research deliberately
excludes the entry minute's potentially pre-purchase high and marks missing
historical structure unmeasurable. The operational 90-minute missing-feed
safety exit remains untouched; it cannot be claimed as proof that the strategy
had no earlier exit. Both differences are tested and disclosed, not hidden
under historical PF. No change to the user's Displacement trading switch.
