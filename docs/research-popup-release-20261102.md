# Research popup release

Scope: modal pair activation, selectable research exit and contract comparisons,
and reuse of exact-scope saved display summaries older than 24 hours.

Research-only choices cannot be activated by the existing permission-only API.
They remain explicitly labeled and disable confirmation. Native pair activation
uses the unchanged endpoint. No selections are automatically saved, no pair is
enabled by deployment and no exit, risk or live-mode settings are changed.

Validation: 184 frontend source/logic regression tests, production TypeScript/Vite
build, and 24 focused snapshot/store/refresh tests pass. These are not browser
interaction or market-session tests. A pre-existing test module isolation problem
was fixed after reproduction individually and in the combined suite.

Rollback: revert this release to 557d4d670cd80110092be5fdb2ab948b79528f5e,
restore the prior frontend index from the release backup and restart the dashboard.
Retain both versions of static assets for already-open tabs. Do not modify trading
settings, historical records or open-position policies. Roll back if modal rendering
or confirmation fails, backend snapshot exceptions appear, or account isolation fails.

Known limits: changed settings/date filters can still have no exact persisted
summary. The broader forward capture audit and production adapters for arbitrary
research test selections are not completed by this UI release.
