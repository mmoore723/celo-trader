# Activation status correction

Previous production 40cf7a66. AMZN activation succeeded; the five-minute
recommendation snapshot retained its pre-activation tradable flag. Resolve exact
current grants when classifying recommendation cards. Do not modify evidence,
execution policies, risk, trading permissions or account mode.

Regression tests cover all registered execution routes and activation/deactivation
with stale evidence. Run combined regression and reconcile before restart.
Rollback this display-only commit if recommendations fail or incorrectly label
enabled pairs. Existing execution routes remain installed through rollback.
