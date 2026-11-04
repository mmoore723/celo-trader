# Learning navigation release

2026-11-03 23:22 EST

Scope: exact strategy/ticker/version learning links from Settings and Learning,
written VWAP 10:30 reference, honest empty practice state, available-example
counts separate from practice score, concept glossary and browser read-aloud
fallback for missing recorded narration. No trading rules, risk or switches change.

Validation: 61 backend regression tests and 193 frontend tests pass. TypeScript
check and production build pass. No schema migration or historical data edits.
Published examples remain real reviewed examples, not generated filler.

Deploy only the scoped commit and freshly built frontend assets. Preserve old
assets and back up the existing index. Reconcile positions/orders before API
restart. Verify pair links, empty libraries and glossary in production.

Rollback if learning routes fail, pair isolation breaks or existing pages fail:
revert this scoped commit and restore /tmp/celo-learning-index-before-20261103.html
to frontend/dist/index.html; restart dashboard after reconciliation. Keep old
assets. No database rollback is needed. Recorded Failed-Range audio is still
absent; browser voice is explicitly labeled, not presented as Coach recording.
