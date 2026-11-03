# Daily Brief execution scope correction

Daily Brief previously combined saved watchlist and scanner hits. Research
universe cleanup did not change this separate path. Filter saved reports at read
time and future builds using exact enabled strategy/ticker permissions for the
current account mode. New enabled names missing from today's saved report can
be built by the existing background worker. No page-triggered market calculation.

No strategy permission, risk setting, live enable or exit change is included.
Research remains separate. A fit score is not a probability or qualification.

Rollback: revert this release commit and restart the dashboard only after
checking positions/orders. Saved Daily Brief evidence is not deleted. Roll back
if the premarket endpoint errors or enabled tickers disappear incorrectly.
