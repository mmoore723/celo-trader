"""Customer preview capabilities. Existing accounts retain their access unchanged."""
from fastapi import HTTPException
import re


def is_customer(user: dict) -> bool:
    return not user.get('is_admin') and user.get('access_profile', 'legacy') != 'legacy'


def enforce_customer_access(user: dict, method: str, path: str) -> None:
    if not is_customer(user):
        return
    profile = user.get('access_profile')
    # Exact allowlist, fail closed for unknown profiles and newly added APIs.
    if profile in {'watch', 'learning'}:
        if method == 'GET' and re.fullmatch(r'/api/market/bars/[A-Za-z][A-Za-z0-9.\-]{0,9}', path):
            return
        if profile == 'learning' and (
            (method == 'GET' and path in {'/api/learning/foundations', '/api/learning/course'}) or
            (method == 'POST' and path in {'/api/learning/foundations/answer', '/api/learning/course/answer'})
        ):
            return
    raise HTTPException(403, 'This account can view charts and its Learning content only. Trading and account controls are not available.')
