# Guided activation review

Scope: recommendation review UI and account-local approval records only.
No execution adapter is introduced or enabled by this change. No risk, strategy,
broker or live-mode setting changes. User approval means implementation/testing
authorization, not an order grant. There is no automatic coding worker.

The modal reads the existing cached research snapshot, never starts a backtest.
It shows training/holdout metrics, missing coverage, current rules, source pins
and blockers. Unknown definitions remain unknown. Exact-rule approval or requested
changes are saved durably to strategy_activation_reviews.sqlite3 under the user
directory, isolated by database/account/mode, strategy/ticker/version and evidence.
Duplicate submissions are idempotent. Changed evidence requires fresh review.
Only a currently executable recommendation can offer separate activation through
the existing revalidated consent endpoint. Existing safety gates remain intact.

Tests: new approval cases cover persistence, idempotence, missing answers,
conflicting answers, changed evidence, forged tokens, admin authorization and
account/mode/version isolation. Full frontend tests and production build required.
Existing recommendation suite currently has 2 failures and 1 error on unchanged
production due to runtime source-review hash mismatches. This release does not
fix those pre-existing execution blocks or claim execution readiness.

Deployment: save current index, deploy only this focused source commit, run
tests on server, reconcile positions/orders before restarting dashboard. Retain
old frontend assets and update index after new assets. Preserve approval database.

Rollback: revert this source commit and restart dashboard only when safe; restore
/opt/celo_release_backups/guided-activation-20261103/index.html to frontend/dist/index.html.
Keep approval records for audit. No trading configuration rollback is necessary.
Rollback on failed API authorization, leaked account scope, modal failures, or
dashboard errors. Verify both services and the live site's read-only review flow.
