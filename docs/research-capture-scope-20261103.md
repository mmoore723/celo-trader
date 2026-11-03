# Research capture scope and approved premium comparison

November 3, 2026. Research only. No trading settings, exits, risk limits or live activation changes.

## Changes

Audit the union of selected research tickers and historical candidate tickers, with selection status shown separately. Historical inactive names are not reenabled.

Use the existing validated, provenance-recorded Tradier session fallback for initial research scans and longer-expiration exits, in addition to authored and profit-protection exits. No invented bars or retrospective replacement of outcomes.

Check authored exits at the existing 30-second between-ticker checkpoint, rather than only before the full scan. This is cooperative scheduling, not a guaranteed 30-second maximum latency during a slow provider request.

User approved a separate research comparison: expiration_8_21_low_premium_v1, nearest eligible expiration 8 through 21 calendar days, nearest OTM contract, ask $0.25 through $1.49, maximum midpoint spread 8%. Original expiration_8_21_nearest_v1 remains $1.50 through $10.00. Contract identity, timestamp freshness and 60-second setup enrollment remain unchanged. Both profiles use the same existing registered authored exit protocol. No order path is available. Profiles are persisted under separate compound keys and captured independently. Existing summaries default to the original profile so they cannot pool outcomes. Low-premium rows are available through profile-scoped ledger reads; no dedicated UI added in this release.

## Validation

128 capture, worker isolation, exit, session-close and risk regression tests; 59 expiration-study tests including profile separation, spread preservation, deduplication, capture and unchanged primary evidence. Both suites must pass on production before restart. Verify actual worker records separately from tests.

## Rollback

Baseline commit 8612cd25. Revert this release commit and restart the dashboard only after checking broker positions and orders. Do not restore an old database or erase new evidence. The old reader ignores the additional profile. Its collection pauses on rollback, and those attempts must be reported as incomplete rather than repriced later.

Roll back for new repeated worker exceptions, account/profile cross-contamination, altered trading settings or inability to serve the app after restart. Preserve open-position management throughout. Missing historic quote prices remain missing; this release does not claim to repair them.
