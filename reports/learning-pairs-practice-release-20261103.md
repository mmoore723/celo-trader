# Compact learning pairs and trade practice

2026-11-03 23:43 EST

Previously practice used chart-complete scanner candidates and their underlying
follow-through, not an executed-trade library. New read-only journal practice
reads the active account and paper/live database separately, matches recorded
strategy versions, and excludes unknown/conflicting versions and partial positions.
No entry correctness is inferred from profit or loss. These are guided outcome
reviews, not secure exams, model training or changes to trading decisions.

Two explicit fictional teaching exercises are available even with no matching
closed trades. They do not enter the database or research metrics. Existing
scanner chart exercises remain separate. No new historical candle reconstruction.

UI: searchable pair selector with Lesson, Reference and Practice actions.
Tests: 65 backend tests; frontend suite, TypeScript and production build.
No schema changes, settings mutations or order paths. Query bounded to500 rows.

Rollback: revert this scoped commit and restore the pre-release index from
/tmp/celo-learning-pairs-index-before.html; preserve old assets. Reconcile
positions and orders before restarting dashboard. Roll back for endpoint500,
incorrect account/version mixing, or broken pair navigation. Verify production
UI and real database results separately from unit fixtures.
