# Exit archive adapters

These are read-only inputs for offline comparison, not an enrolled experiment.
`ExitArchiveReader` reads the user's existing session, option and native decision
SQLite archives with read-only connections, bounded row counts and query deadlines.
No trading callers, background jobs, migrations or configuration changes are added.

Option data requires an exact account, mode, strategy, ticker, version, contract,
trade ID and entry timestamp match to a broker-trade registration. This verifies
registration identity, not broker fill authenticity. Callers still need verified
entry-fill evidence. Research-only registrations are not broker trades.

Stock last-trade snapshots preserve source and receipt timestamps. Snapshot
fingerprints are not exchange sequence numbers or proof of tick-complete capture.
Wrong feeds, missing timestamps and later-recovered history are rejected. Rejected
records are reported separately. No missing bid size or price is invented.

The option archive's original validation is retained. Frozen experiment freshness,
spread, quantity and receipt-gap requirements must still run in the pricing engine.
Native records must pass the native-request adapter's context and quantity checks.
These readers do not certify complete decision coverage, causal entry-level
availability, experiment approval or qualification. The entry-level adapter now
checks the linked original candidate against the trade's frozen context, account,
version, contract and fill clock. It supports only the existing structural_levels
schema with explicit completed-bar and recorded timestamps. Unmapped raw level
fields remain blocked, not inferred. Broker fill reconciliation remains separate.
Registration metadata copied after entry is not accepted as original evidence.
Empty archives are not successful tests. Reads have row, byte and time limits.

## November 9 capture performance repair

Registered-option capture adds indexes for contract-window lookup and registration
receipt lookup. Repeated unchanged registration discovery no longer opens write
transactions. Request timestamps are taken immediately before the request, not
before discovery. Saved health separates discovery, due query, request and persist
durations. These are capture-only changes; provider quotas and trading stay fixed.
Index construction happens at collector startup. Existing observations and their
timestamps are not rewritten. Rollback uses deploy.sh to restore prior worker
code; additive indexes may remain safely. No data deletion is required. Actual
next-session cadence must still be measured before claiming the gaps are fixed.

Discovery now runs in a single background task with its own SQLite connection.
No second task is queued while it runs. Existing registered contracts continue
polling. Failed discovery reports an explicit blocker and is retried; results
from a prior account cannot label a different account ready. Health reports
discovery elapsed time. The one-shot diagnostic command remains synchronous.
This isolates discovery latency, not CPU usage; real market cadence still needs
verification under the service's existing CPU and memory limits. Roll back this
worker change via deploy.sh if contention, memory pressure or collection failures
increase. Keep stored observations and existing indexes unchanged.

## Release and rollback

Run the complete deploy.sh regression gate and verify GitHub/production identity.
Focused tests use the real capture writers with synthetic observations and check
paired pricing, account isolation, missing timestamps/sizes, provenance, bounded
reads, no archive creation and no record mutation. No market result is claimed.

If archive readers produce incorrect identity/provenance, mutate data or cause
resource problems, stop their research caller and revert this additive release
through deploy.sh. Preserve all archives. No exit policy, open-position state,
account risk or live-trading switch needs changing for rollback. The release adds
no scheduled caller, so installation alone cannot affect collection or execution.
