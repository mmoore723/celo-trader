# Beginner lessons and right-hand coach

UI only. No trading, account, strategy, risk, order or database changes.
Explain all 25 existing chart steps using meaning plus an example. Keep technical
rules unchanged. Revised lesson narration uses labeled browser read-aloud so it
matches the visible explanation instead of playing an older script.
Remove explanation disclosures. Show one selected topic at a time with all text.
Coach Celo remains the right-hand column at every breakpoint. Narrow viewports
scroll the chart/coach region horizontally instead of stacking Coach below it.
Remove the duplicate pointing character inside the chart, retaining its focus cue.

Preflight: TypeScript, full frontend suite, production build and source diff check.
Deploy assets then index atomically. No restart. Verify chart/coach placement and
visible beginner copy in production.
Rollback on broken chart/navigation/layout: restore /tmp/celo-beginner-index-before.html
and revert the scoped commit. Keep older assets. No data rollback.
Do not claim a 15-minute soak or all screen sizes visually checked unless observed.
