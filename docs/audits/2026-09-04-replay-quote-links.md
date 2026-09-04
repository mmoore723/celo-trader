# Replay quote identity repair — September 4, 2026

## Defect and scope

The event tape treated every event beginning with `trade_` as a trade row.
For `trade_quote`, its row ID identifies the quote, not the trade. This could
hide an existing exit quote or count a quote ID as proof that a trade existed.
Previous fixtures accidentally used matching quote and trade IDs.

Only actual `trade_entry` and `trade_exit` rows now supply trade identities.
Quote events retain their own event ID and use their recorded `trade_id` link.
Replay accepts only actual trade events as evidence that a position exists.

No entry, exit, pricing, risk, broker, credential, setting, schema, or historical
record changes. This corrects evidence links, not order placement or profits.
An exit quote record is not proof of a fresh, executable bid. The separate
fill-fidelity audit still reports missing prices and unverified freshness.

## Regression verification

Six new checks cover differing IDs, correct exit linkage, orphan quotes,
broker fills incorrectly pointing at quotes, account isolation, and multiple
marks that must not inflate exit coverage. Four failed before this repair.
The 31-test focused local suite passes, including existing scorecard, strategy
replay, performance-account-scope, fill-fidelity, and broker-audit checks.

## Release checklist

- Stage the exact commit on the server; run the focused and execution suites
  against isolated fixtures, not production database writes.
- Verify the expected base and allowlisted diff; preserve unrelated files.
- Do not interrupt an open position. Check paper broker positions, working
  orders, journal positions and unresolved recovery state before stopping.
- Back up current source, settings, state, and the database. Recheck broker
  exposure after stopping, before changing source; restart unchanged if unsafe.
- Restart the narrow release, check health and unchanged protected settings,
  then inspect 15 minutes of operation and current broker connectivity.
- Roll back source only if health, lifecycle or scanning regresses. Never
  restore historical database/state backups over newer trade activity.

Deployment results belong in the dated workspace handoff. This checklist
does not itself claim that deployment or post-release monitoring is complete.
