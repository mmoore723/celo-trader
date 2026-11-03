# Partial research candle recovery

Production probe at13:28 Eastern: PLNT primary missed170 completed minutes,
Tradier missed43; SAIL primary missed115, Tradier missed5. Neither replacement
lost an existing primary completed minute. The complete-session-only requirement
discarded127 and110 recoverable minutes respectively.

Accept validated Tradier OHLC only when its missing-minute set is a strict subset
of the primary's. Never merge providers or synthesize a candle. Partial recovery
is marked tradier_session_1m_partial_recovery_v1, with remaining gaps exposed in
frame attributes and logs. Stored request time and original bars permit exact
recalculation of gaps. Existing per-policy required-window checks are unchanged.
Original historical failed outcomes stay unchanged. Trading readers and exits
are not modified.

Validation covers partial success, losing existing minutes, unchanged coverage,
invalid OHLC, duplicate bars, previous sessions, worker isolation and existing
exit/session-close regressions. Require server tests and broker reconciliation
before restart; verify actual worker source records after deployment.

Rollback baseline334ae3c8: revert this commit and restart dashboard after checking
open positions/orders. Preserve the additive source evidence. Roll back if invalid
bars are accepted, required-window checks are bypassed, or worker errors increase.
No database restore, ticker reactivation or trading-setting change is required.
