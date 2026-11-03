# Halt banner layout repair

The app shell defines only topbar, sidebar and main grid areas. Broker/halt
banners were extra unassigned grid children. An active halt created implicit
sidebar-sized cells and clipped controls. Move both banners into a sticky,
height-bounded scrollable region within main. Distinguish HTTP200 ok:false
resume rejection from success, retaining the server explanation.

Production logs show resume POSTs at17:01:14 and17:01:33 UTC. The configured
soft daily loss limit is10%, day-open1991.37 and logged realized loss282.00.
Resume intentionally cannot bypass the breached199.137 allowance.

Frontend-only deployment. No settings, risk thresholds, lock files, orders,
strategy exits or backend restart changes. Prior release f2ce0ba8.
Rollback: restore frontend/dist/index.html from
/opt/celo_release_backups/halt-banner-20261103/dist/index.html.
Retain previous hashed assets. Roll back for asset errors or inaccessible
controls. Verification must not submit a resume or order request.
