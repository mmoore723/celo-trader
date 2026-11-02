# Trading overview and confirmation repair

Frontend-only release. Trading now uses saved catalog permissions, a searchable
strategy/ticker/version table, an isolated pair detail panel, realized P&L bars,
and wins versus other closed outcomes. No invented equity curve, pooled winner,
or research simulation appears as an actual trade. Missing records and failed
requests show unavailable, not zero profits. Other versions and account modes
are excluded. Controls and audit evidence remain available on demand.

Pair activation and research comparison are separate popup screens. Browsing a
research variant no longer leaves a disabled confirmation button. Returning to
activation clearly confirms current production rules only. Production adapters
for research variants are still not implemented and this release does not pretend
to activate those variants. Existing permission endpoint and safety checks remain.

Browser validation used the actual components with a local mock API. Selected
both test types, returned to activation and confirmed the exact pair payload.
Verified switching SPY to QQQ changes metrics independently and inspected the
rendered charts. This was not an actual production activation or broker order.

Deployment: static frontend update only. No service restart required. Keep old
assets for existing tabs. No settings, exits, live status or risk changes.

Rollback: restore the prior frontend index and assets from
/opt/celo_release_backups/trading-overview-20261102/dist. Previous revision:
f63845f33f8baf382ca7a22c14ac13728eaa5b27. Revert the scoped source commit as well.
Rollback triggers: blank settings/research pages, broken native confirmation,
incorrect account/version metrics or failed asset requests. Never roll back trade
history, research observations, account settings or open-position policies.
