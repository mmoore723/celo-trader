#!/bin/bash
# Build frontend + push to git so EC2 can pull the new bundle
set -e

cd "$(dirname "$0")/frontend"
echo "→ Building frontend..."
npm run build

cd ..
echo "→ Committing new dist..."
git add frontend/dist frontend/src/lib/api.ts
git commit -m "fix: rebuild dist with session cookie fix" 2>/dev/null || echo "(nothing new to commit)"
echo "→ Pushing..."
git push

echo ""
echo "✅ Done! Now run on EC2:"
echo "   cd /opt/celo_trader && git pull && sudo systemctl restart celo-dashboard.service"
