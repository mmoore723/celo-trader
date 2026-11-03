# Activation selection release

November 3, 2026. Previous production source: dbd1808b.

Settings and Research use one selection dialog. Explicit admin confirmation
stores exact exit minutes and contract choice for that pair/version. No setting
changes on deployment or dialog opening. Original positions retain their frozen
policy; safety/session exits and risk limits are unchanged. New runtime review
pins reviewed sources without modifying historical profitability evidence.

Validation: 188 backend execution/recovery/research tests and 192 frontend tests
pass locally. Browser mock confirms QQQ research.1 payload includes 90 minutes
and closest OTM, without production requests. Build passes. Server regression,
reconciliation, service health and public assets are required before completion.

Rollback: save deployed index to /opt/celo_release_backups/activation-selection-20261103/index.html.
Restore that index immediately if the dialog fails. Retain hashed assets.
Revert the scoped source commit and restart only after fresh reconciliation
confirms no positions or pending orders. If positions opened under the new policy,
keep its version-aware management running until they close; never roll back to
code that would ignore their frozen policy. No historical records are rewritten.
Rollback triggers: integrity errors, failed reconciliation, selected policy not
round-tripping, repeated API errors or a failed execution regression. Do not
activate a strategy as a deployment smoke test.

Unrelated capture storage patch 0d2ecac is deliberately excluded.
