# GitHub reconciliation, November 4 2026

GitHub main was b5e9c633, 89 commits behind deployed bd08defa. Manual releases
bypassed deploy.sh, which already pushes to GitHub before updating EC2.

Recovery preserves the production commit history as a fast-forward. It also
commits the already-served frontend build. The source and trading behavior are
unchanged; no service restart is required. Added release instructions explicitly
require GitHub and production commit equality before calling a release complete.

Verification: credential-pattern scan across unpublished added lines, no large
blobs above 90 MB, source ancestry, identical served/local index SHA256, and the
existing 205-test frontend acceptance run for the exact published build.
The credential scan is a targeted check, not a guarantee no secret can exist.

Rollback: do not reset GitHub or force-push history. This reconciliation changes
no running code. If metadata reconciliation fails, leave EC2 running its existing
build, report the mismatch, and repair the commit reference only after file hashes
match. Existing release rollback index remains
/tmp/celo-orb-pointer-index-before.html for the earlier UI change.

An embedded credential in the server's local Git remote needs rotation separately.
It is not part of the Git repository and is not included in this publication.
