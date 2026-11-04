# Learning family release

Frontend only. No trading settings, backend policy, risk, database or execution changes.
Restore the existing five chart walkthroughs visibly. Group enabled variants into
teaching families and remove the ticker/strategy search. Select variation/version
inside a family. Ticker selection is only account-policy and practice context.
Version-specific entry and exit reference plus rule diagram accompany source charts.
Source charts are explicitly examples, not a replay of selected policy overrides.
Explain actual full-debit sizing versus hypothetical premium-stop sizing.

Known limitation: not every enabled variation has an authored annotated price chart.
These variations expose their written reference and an explicit chart-content gap.
No invented charts, trades or inferred policy rules. Historical versions are not
substituted for current ones. Existing five chart scripts remain source examples.

Preflight: TypeScript, all frontend tests, isolated build, scoped diff review.
Publish assets first and index last. No service restart required.
Rollback if learning fails to render or navigation breaks: restore
/tmp/celo-family-index-before.html to frontend/dist/index.html and revert the scoped
source commit. Retain old assets. No database rollback required.
Browser checks and public bundle check required. Do not claim a 15-minute soak
unless actually observed.
