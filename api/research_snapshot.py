from collections import OrderedDict
from contextvars import copy_context
from hashlib import sha256
import json
from threading import Lock, Thread
from time import monotonic, time
import logging

from fastapi import HTTPException

_cache = OrderedDict()
_guard = Lock()
_build = Lock()
TTL_SECONDS = 60
BUILD_WAIT_SECONDS = 45
DISPLAY_MAX_AGE_SECONDS = 300
MAX_SNAPSHOTS = 6


def research_snapshot(days=90, *, start_date=None, end_date=None, allow_stale=False):
    from auth.context import get_current_user_id
    from config import get_db_path, get_settings
    from strategy_health.research_matrix import build_research_matrix

    days = max(1, min(int(days), 365))
    settings = dict(get_settings())
    settings.pop("last_known_balance", None)
    settings_digest = sha256(json.dumps(settings, sort_keys=True, default=str).encode()).hexdigest()
    key = (get_current_user_id(), str(get_db_path()), settings_digest, days, start_date, end_date)

    def cached(max_age=TTL_SECONDS):
        with _guard:
            entry = _cache.get(key)
            if entry is not None and monotonic() - entry[0] < max_age:
                return entry
        return None

    def response(entry):
        if not allow_stale:
            return entry[1]
        return {**entry[1], "snapshot": {
            "updated_at": entry[2],
            "refreshing": monotonic() - entry[0] >= TTL_SECONDS,
        }}

    def rebuild():
        result = (build_research_matrix(days, start_date=start_date, end_date=end_date)
                  if start_date is not None or end_date is not None else build_research_matrix(days))
        entry = (monotonic(), result, time())
        with _guard:
            _cache[key] = entry
            _cache.move_to_end(key)
            while len(_cache) > MAX_SNAPSHOTS:
                _cache.popitem(last=False)
        return entry

    result = cached()
    if result is not None:
        return response(result)
    stale = cached(DISPLAY_MAX_AGE_SECONDS) if allow_stale else None
    if stale is not None:
        if _build.acquire(blocking=False):
            def refresh():
                try:
                    rebuild()
                except Exception:
                    logging.getLogger(__name__).exception("Research display refresh failed")
                finally:
                    _build.release()
            try:
                Thread(target=copy_context().run, args=(refresh,), daemon=True).start()
            except Exception:
                _build.release()
                raise
        return response(stale)
    if not _build.acquire(timeout=BUILD_WAIT_SECONDS):
        raise HTTPException(status_code=503, detail='Research results are refreshing. Retry shortly.',
                            headers={'Retry-After': '5'})
    try:
        result = cached()
        if result is None:
            result = rebuild()
        return response(result)
    finally:
        _build.release()
