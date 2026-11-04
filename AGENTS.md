# Celo Trader release rules

Use deploy.sh for normal releases. Do not bypass its GitHub push with manual
bundles, cherry-picks or asset copies and then declare deployment complete.
If the script is blocked, diagnose and report the blocker instead of silently
choosing another path. A narrowly scoped recovery must still publish the exact
deployed source and matching frontend build to GitHub.

Before declaring a release complete, query GitHub main directly, compare its
commit with production, and verify that the served frontend belongs to that
release. Report mismatches explicitly. Never force-push to reconcile deployments.
Never publish secrets, runtime account data or unrelated local research files.

Preserve unrelated changes. Document rollback before deployment. Deployment does
not authorize trading-policy changes, live enablement, orders or risk changes.
When working in the Stock workspace, read and update CELO_CURRENT_STATUS.md.
