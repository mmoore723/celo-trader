# AMZN VWAP activation release

Previous production: 2ddd29dd. Register AMZN VWAP Pullback research.1 only.
Use the existing research engine, five-minute completed bars and original
structural stop/2R target protocol. Explicit selected timers replace that protocol
for new entries only. Session liquidation and account safety remain active.
No strategy is enabled by deployment; no risk or live-mode setting is changed.
Keep historical evidence intact. This is execution support, not profit validation.

Validate entry parity in both directions, exact pair grants, selected deadline
during quote outage, structural exits, restart/partial-fill/duplicate protection
and the combined existing regression. Reconcile broker before service restart.

Rollback on integrity errors, activation errors or failed execution regression:
revert this release and restart only after checking positions/orders. If AMZN
VWAP positions have been opened, retain their frozen exit manager until closed.
Never remove an open position's manager or reset risk as a rollback shortcut.
No migrations and no unrelated capture-storage changes are included.
