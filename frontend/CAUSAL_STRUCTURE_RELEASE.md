# Chart confirmation labels

Display-only release. No strategy, order, risk, account or exit-policy changes.

Five bars on either side confirm pivots. Labels appear on the following bar,
not back on the high/low. The current forming candle cannot confirm a swing or
trigger a displayed break. Higher/lower swings are labeled as confirmations,
not automatically called BOS/CHoCH. Completed closes through already confirmed
swings generate explicitly bullish or bearish break labels. Opposite breaks
change direction; repeated-direction breaks are BOS. This remains chart context,
not a new execution policy or proof of historical data receipt timing.

The prior data-length-dependent confirmation window is removed. Legacy backend
structure markers without confirmation timestamps are suppressed. Only the last
18 chart structure labels are rendered for legibility; underlying computation
is not limited to those 18 labels. No full historical chronology is claimed when
the user loads a shorter history.

Regression: pivot confirmation delay, forming-bar exclusion, bullish/bearish
labels and prefix stability at 100/200/400-bar thresholds. Normal deploy.sh
must run full Python/frontend tests, lint and build before release.

Rollback triggers: blank chart, marker rendering errors, or confirmation labels
appearing before confirmation. Revert only this release's frontend source changes,
rebuild and redeploy through deploy.sh. Preserve all capture evidence and account
settings. Previous production base: 41d314784ac2bfda454b098bad1fa8ffa2542775.
No database migration is involved.
