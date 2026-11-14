"""Research evidence is internal. Actual account journals remain account scoped."""
from fastapi import Depends, HTTPException, Request
from api.middleware.auth import require_auth


async def require_research_admin(request: Request, _=Depends(require_auth)):
    if not getattr(request.state, 'is_admin', False):
        raise HTTPException(403, 'Research is available to administrators only.')


async def require_internal_review(request: Request, _=Depends(require_auth)):
    # These two endpoints describe the authenticated account's own trades.
    if request.url.path in {'/api/strategy-health/scorecard', '/api/strategy-health/daily-scorecard'}:
        return
    if not getattr(request.state, 'is_admin', False):
        raise HTTPException(403, 'Research is available to administrators only.')


async def scoped_opportunity_feed(request: Request, _=Depends(require_auth)):
    feed = request.query_params.get('feed')
    if getattr(request.state, 'is_admin', False):
        return feed
    if feed == 'research':
        raise HTTPException(403, 'Research is available to administrators only.')
    return 'operational'
