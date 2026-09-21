from collections import OrderedDict
from hashlib import sha256
import json
from threading import Lock
from time import monotonic

from fastapi import HTTPException

_cache = OrderedDict()
_guard = Lock()
_build = Lock()
TTL_SECONDS = 60


def research_snapshot(days=90):
    from auth.context import get_current_user_id
    from config import get_db_path, get_settings
    from strategy_health.research_matrix import build_research_matrix

    days = max(1, min(int(days), 365))
    settings_digest = sha256(json.dumps(get_settings(), sort_keys=True, default=str).encode()).hexdigest()
    key = (get_current_user_id(), str(get_db_path()), settings_digest, days)

    def cached():
        with _guard:
            entry = _cache.get(key)
            if entry is not None and monotonic() - entry[0] < TTL_SECONDS:
                return entry[1]
        return None

    result = cached()
    if result is not None:
        return result
    if not _build.acquire(blocking=False):
        raise HTTPException(status_code=503, detail='Research results are refreshing. Retry shortly.',
                            headers={'Retry-After': '5'})
    try:
        result = cached()
        if result is None:
            result = build_research_matrix(days)
            with _guard:
                _cache[key] = (monotonic(), result)
                _cache.move_to_end(key)
                while len(_cache) > 2:
                    _cache.popitem(last=False)
        return result
    finally:
        _build.release()
