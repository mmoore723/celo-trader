# Research enable control repair

Scope: frontend only. Keep existing confirmation endpoint, permissions, safety
checks, trading settings, risk limits and exit policies unchanged.

The saved flag replaced the action button for the lifetime of the mounted row.
Keep the action available after success and clear the success notice on reopen.
Rename the navigation tab from Enable strategy to Trading permission so it is
not confused with the actual Confirm turn on action.

Validation: all 187 frontend tests pass; TypeScript and production build pass.
Browser fixture with mocked API verified exact strategy/version/ticker payload,
successful confirmation, retained action and reopening after success. Production
popup navigation was inspected without submitting a real enable request.

Deployment: retain old hashed assets, upload new assets before replacing index.
No service restart or settings write required.

Rollback: restore frontend/dist/index.html from
/opt/celo_release_backups/research-enable-repeat-20261102/dist/index.html.
Old assets remain available. Revert this focused source commit if necessary.
Roll back if popup navigation breaks, frontend crashes, or asset loading fails.
No database restore or policy rollback is needed.
