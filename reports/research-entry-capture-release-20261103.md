# Research capture validation release

Scope: research capture only. No strategy grants, orders, risk limits, account
mode, live enablement or deployed exit policies change.

## Findings and corrections

The expiration-study selector used worker observation time for its 60-second
freshness limit. A delayed scan could enroll a six-minute-old signal. Both
selection and ledger validation now anchor freshness to the original signal.
Selection retains observation time and a capture revision separately.

Timed studies could enroll with deadlines after the regular session ended.
These are now explicitly unmeasurable rather than given a different exit time.
This guard uses the existing study's regular-session boundary. It does not
implement an exchange early-close calendar or change trading liquidation rules.
Completed historical results are untouched. Invalid active attempts preserve
their original state in an append-only validation record when finalized.

At pass startup, expensive diagnostics and profit-path work ran before authored
exit capture was initialized. Authored and expiration exits now run first.
Already-triggered authored exits precede collecting attempts. There is no new
execution thread or order capability.

Closing quote validation now retains decision, request and receipt timestamps,
available bid/ask sizes and source timestamps, plus an explicit rejection reason.
Records are bounded to one outcome per candidate/protocol/decision/minute.
Pricing deadlines and freshness rules are unchanged. Diagnostics cannot create
a fill. Existing failed results are not repriced.

## Provider evidence

Fresh Tradier reads after the November 3 session still return 344 PLNT bars and
381 SAIL bars, leaving 46 and 9 missing regular-session minutes respectively.
Explicit Eastern-time narrow requests also omit PLNT 09:37 and SAIL 10:04 while
returning neighboring bars. This confirms omissions in the supplied history,
not whether the exchange had zero qualifying trades. No candles are invented.
These gaps remain unresolved provider-data blockers for affected tests.

## Tests and release gates

333 combined unit/integration regressions passed locally. Coverage includes
signal-time rejection, infeasible horizons, append-only active-attempt repair,
stale/future/wrong-contract quotes, account isolation, restart/CAS behavior,
capture ordering, all study protocols and execution safety regressions.
An initial run found a runtime-source manifest mismatch for Compression. The
new append-only runtime manifest now includes the changed capture sources;
historical evidence manifests were not edited. Integrity check returns no errors.

Before restart: repeat tests on server, verify zero DB positions, broker
positions and open orders, preserve settings and document the deployed commit.
The market is closed. No new-session forward coverage is claimed.

## Rollback

Revert this single release commit, restoring the prior runtime selector and
capture code. Restart the dashboard only after safe broker reconciliation.
Keep the additive diagnostic/validation tables and all historical records.
Do not reverse validated evidence into fabricated priced results. Roll back if
runtime integrity fails, startup fails, capture exceptions persist, or API
responsiveness materially regresses. No account/risk/strategy changes to undo.

Remaining verification: actual next-session capture and session-close quotes.
Missing provider bars and unavailable historical option quotes cannot be
declared repaired by passing unit tests.
