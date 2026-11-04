# Header and learning navigation cleanup

2026-11-03 23:49 EST. Frontend only.

Remove Watching/ticker from global header. Keep one enabled-pair chooser on
Learning Hub instead of also mounting the legacy five-course browser with its
separate strategy selection. Hide redundant one-course tabs in pair walkthroughs.
Pair lessons, references, actual-trade practice and scanner chart practice remain.

TypeScript, frontend regression suite and production build must pass before deploy.
No backend restart, settings mutation or trading-policy change required.
Publish new assets before atomically replacing index. Keep older assets.

Rollback for broken navigation/rendering: restore
/tmp/celo-header-index-before.html to frontend/dist/index.html and revert the
scoped source commit. No database changes or restart required.
