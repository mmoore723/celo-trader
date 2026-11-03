# Temporary daily loss limit

Resume trading opens a native modal. The user chooses existing limits or an
explicit total-dollar daily loss limit. No default override or automatic resume.
The override includes prior realized losses and equity loss from day-open.
Both daily caps use that amount, scoped to the current user, broker account and
paper/live mode. It expires at midnight Eastern. Permanent settings stay intact.
No strategy exit, live enable flag or order submission is changed by deployment.

Broker and journal must be flat, with no orders or pending emergency fills.
Current broker equity and realized losses are checked before writing the override.
The amount must be finite, positive, greater than current losses and no greater
than day-open equity. A stale date or scope is rejected. Atomic storage survives
restart. Invalid current-date records block entries. Guard and resume serialize
within the application's single bot/API process to avoid re-halting on old limits.

Verification: focused backend risk tests, frontend suite and production build.
Production popup is tested without submitting resume. Real broker resume is left
to the user; automated tests use mock broker reconciliation.

Rollback: revert this release's source commit, restore the previous built index
from /opt/celo_release_backups/resume-limit-20261103/dist, keep old assets, and
restart celo-dashboard after reconciling open positions. Do not delete halt or
override evidence. Previous code enforces original daily caps, so an active
override may cause a renewed halt. Existing positions must retain exit management.
Rollback on failed health checks, wrong account/mode isolation or guard errors.
