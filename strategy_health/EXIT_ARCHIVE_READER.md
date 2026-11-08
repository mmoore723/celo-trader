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
availability, experiment approval or qualification. They do not infer levels from
registration metadata copied after entry. Empty archives are not successful tests.

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
