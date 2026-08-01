"""
broker/tradier_core.py — TradierCoreMixin: auth headers and the shared GET
helper (with its HTML/JSON error-body handling and retry wrapper).

Split out of the old single broker.py (2026-08-01, file-size cleanup); no
logic changed, only relocated. Combined with the other Tradier*Mixin classes
into TradierClient in broker/tradier_client.py.
"""

import logging

from config import TRADIER_API_KEY, TRADIER_BASE_URL
from database import log_event
from logger_config import _LatencyTimer
from broker.common import _retry, _debounced_log

logger = logging.getLogger("celo_trader.broker")


class TradierCoreMixin:

    def __init__(self):
        from config import get_api_keys as _gak
        _keys = _gak()
        _key  = _keys.get("tradier_api_key", TRADIER_API_KEY)
        self.base    = TRADIER_BASE_URL
        self.headers = {
            "Authorization": f"Bearer {_key}",
            "Accept":        "application/json",
        }
        if not _key:
            logger.warning("Tradier API key not set — options data unavailable")

    def _get(self, endpoint: str, params: dict = None) -> dict:
        url = f"{self.base}{endpoint}"
        def call():
            with _LatencyTimer(logger, "tradier_http_get", endpoint=endpoint):
                r = requests.get(url, headers=self.headers, params=params, timeout=10)
                r.raise_for_status()
                # Tradier sandbox endpoints occasionally return an empty body
                # (e.g. /markets/fundamentals/calendars on free-tier keys).
                # Guard against JSONDecodeError so the retry loop is not triggered
                # for a quota/permissions issue that won't resolve on retry.
                if not r.text or not r.text.strip():
                    logger.warning(
                        "tradier_empty_body: %s returned empty response — skipping retries",
                        endpoint,
                    )
                    return {}   # safe empty dict; callers check .get() with defaults
                # Tradier occasionally returns an HTML error page or XML quota
                # response (especially on free-tier rate limits) that causes
                try:
                    return r.json()
                except Exception as _jde:
                    _ctype = r.headers.get("Content-Type", "")
                    _body  = r.text[:300]
                    # Detect the specific case where Tradier (or a proxy in front of
                    # it) silently redirected us to its ReadMe.io-hosted docs/marketing
                    _is_docs_redirect = (
                        "text/html" in _ctype.lower()
                        or _body.lstrip().lower().startswith(("<!doctype", "<html"))
                    )
                    logger.error(
                        "tradier_json_decode: %s status=%d url=%s redirected_to=%s "
                        "content_type=%s body=%r error=%s",
                        endpoint, r.status_code, url, r.url, _ctype, _body, _jde,
                    )
                    if _is_docs_redirect:
                        # Debounced (5 min) — this fires every poll cycle otherwise
                        # and floods the Live Trading audit log with duplicates.
                        _debounced_log(
                            "ERROR", "broker.tradier",
                            f"🔴 [Tradier] {endpoint} returned an HTML page instead of "
                            f"JSON (status {r.status_code}) — this looks like a "
                            f"redirect to Tradier's documentation/marketing site, "
                            f"usually caused by an invalid/expired TRADIER_API_KEY or "
                            f"an endpoint not enabled for this account. Retrying will "
                            f"NOT fix this — verify your Tradier sandbox API key and "
                            f"TRADIER_BASE_URL in .env."
                        )
                    else:
                        _debounced_log(
                            "ERROR", "broker.tradier",
                            f"🔴 [Tradier] Received an unreadable response (not JSON) — "
                            f"status {r.status_code}. This often means a rate-limit or "
                            f"server issue."
                        )
                    return {}
        try:
            result = _retry(call)
            # 2026-07-31: clear the alert window on a good call — see broker_health.py
            try:
                from broker_health import record_broker_success
                record_broker_success("tradier")
            except Exception:
                pass
            return result
        except Exception as e:
            log_event("ERROR", "broker.tradier",
                      f"🔴 [Tradier] Connection failed — could not reach the API. "
                      f"Check your internet or API key. ({type(e).__name__})")
            logger.error(
                "tradier_get_failed",
                extra={"event": "tradier_get_failed", "endpoint": endpoint, "error": str(e)},
            )
            # 2026-07-31: feed the dashboard alert banner — see broker_health.py.
            try:
                from broker_health import record_broker_error
                record_broker_error("tradier", f"{endpoint}: {e}")
            except Exception:
                pass  # never let alerting itself break a trade path
            raise
