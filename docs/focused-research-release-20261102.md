# Focused research selection

Scope: configure admin research to the user's 15 familiar tickers plus the 7
existing execution tickers, 22 total. The latest request asks why the UI has not
been cleaned after agreeing to exclude the others. No strategy permission, exit,
risk or live-mode changes are part of this release.

Apply the selected universe before Research Results pagination and analytics,
including ticker selectors and result counts. Use the same account-scoped setting
for future research-worker setup enrollment, independent of the daily shortlist.
Historical raw snapshots remain reusable because filtering happens at response
time. Account, mode, permission and date cache separation remains unchanged.
Pending research exits run before the selected-new-setup loop and remain intact.

No database deletion or archive is performed in this release. The user does not
want research archives. Physical deletion remains unfinished and must not remove
actual trade evidence or records needed for pending/open positions. Do not claim
this display/collection release freed storage. The daily trading scanner/UI is
not redesigned in this release.

Validation: focused-universe, analytics, snapshot persistence, worker isolation
and research-pass regression suites. Verify current production revision and a
clean tracked worktree before fast-forward deployment. Run tests on the server
before restart. Compare settings before/after and require that only
research_tickers changed. Verify displayed results include only the 22 approved
research names, with counts computed after filtering. Actual next-session new
setup collection remains pending while markets are closed.

Rollback triggers: Research API errors, excluded tickers leaking into results,
missing retained ticker results, or any execution-path change. Restore prior code
revision 8993f667 using a scoped revert and restart the dashboard. Remove only
the newly introduced research_tickers setting if reverting to the previous
research enrollment behavior. Do not restore databases, trade history, risk
settings, permissions, position policies, or account mode. No database migration.
