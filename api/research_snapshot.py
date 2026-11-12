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
DISPLAY_MAX_AGE_SECONDS = 86400
MAX_SNAPSHOTS = 6


def research_snapshot(days=90, *, start_date=None, end_date=None, allow_stale=False, force_refresh=False):
    from auth.context import get_current_user_id
    from config import get_db_path, get_settings
    from strategy_health.research_matrix import build_research_matrix

    days = max(1, min(int(days), 365))
    settings = dict(get_settings())
    settings.pop("last_known_balance", None)
    # This selects future observation and filters the response, not historical
    # evidence generation. Keep existing exact-account/date display caches usable.
    settings.pop("research_tickers", None)
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
        try:
            from api.research_display_store import save
            save(key, entry[2], result)
        except Exception:
            logging.getLogger(__name__).exception("Research display snapshot persistence failed")
        return entry

    result = None if force_refresh else cached()
    if result is not None:
        return response(result)
    if allow_stale:
        # Display only: an old exact-scope snapshot is preferable to a blank page.
        # Authorization callers still require the normal fresh path.
        stale = cached(float('inf'))
        if stale is None:
            from api.research_display_store import load
            stored = load(key)
            if stored is not None and 0 <= time() - stored[0]:
                stale = (monotonic() - (time() - stored[0]), stored[1], stored[0])
                with _guard:
                    _cache[key] = stale
                    while len(_cache) > MAX_SNAPSHOTS:
                        _cache.popitem(last=False)
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
        if stale is not None:
            return response(stale)
        raise HTTPException(status_code=503, detail="The saved display for these settings and dates is refreshing. Recorded research has not been reset. Retry shortly.",
                            headers={"Retry-After": "5"})
    if not _build.acquire(timeout=BUILD_WAIT_SECONDS):
        raise HTTPException(status_code=503, detail='Research results are refreshing. Retry shortly.',
                            headers={'Retry-After': '5'})
    try:
        result = None if force_refresh else cached()
        if result is None:
            result = rebuild()
        return response(result)
    finally:
        _build.release()
