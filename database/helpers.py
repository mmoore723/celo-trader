"""
database/helpers.py — Small shared helpers: the ET "now" timestamp used
by every write in this package, ISO-format conversion, and the annotations-
JSON merge helper used by close_trade().

Split out of the old single database.py (2026-08-01, file-size cleanup); no
logic changed, only relocated.
"""

import logging
from datetime import datetime
from typing import Optional

import pytz

logger = logging.getLogger("celo_trader.database")

# ── Timezone helper ───────────────────────────────────────────────────────────
_ET = pytz.timezone("US/Eastern")


def _now_et() -> datetime:
    """
    Return the current wall-clock time in US/Eastern as a tz-aware datetime.
    All timestamps stored in this module use this function so the database
    always records ET times regardless of server locale or UTC offset changes
    (e.g. DST transitions).
    """
    return datetime.now(_ET)




def _to_et_datetime(value: datetime | str) -> datetime:
    """Return one timezone-aware Eastern datetime from broker or local input."""
    dt = value
    if isinstance(value, str):
        dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    if dt.tzinfo is None:
        return _ET.localize(dt)
    return dt.astimezone(_ET)


def _to_et_isoformat(dt: datetime | str) -> str:
    """
    Normalise any datetime to a tz-naive US/Eastern ISO string.

    Two cases:
      • tz-naive  → assumed to already be in ET (all bar timestamps, sim times,
                    and _now_et().replace(tzinfo=None) are ET-naive). Localize
                    directly to ET so DST is acknowledged, then strip tzinfo so
                    the stored string is tz-naive ET.
      • tz-aware  → convert to ET, then strip tzinfo.

    Why tz-naive output?
      The Plotly chart's x-axis is built from df["time"] which is tz-naive ET
      (produced by bars_to_df()). Storing tz-aware strings would cause Plotly to
      UTC-shift marker positions away from their candle — the most common symptom
      is markers appearing 4 hours to the left of the bar they belong to.
    """
    dt = _to_et_datetime(dt)
    # Return without tzinfo so the string matches tz-naive chart timestamps
    return dt.replace(tzinfo=None).isoformat()


def _merge_annotations_json(existing: Optional[str], new: Optional[str]) -> Optional[str]:
    """
    Combine two JSON-encoded annotation lists (e.g. entry-time + exit-time
    snapshots) into one, deduped by the annotation's own "id" field.
    Never raises — malformed/missing JSON on either side is treated as empty
    so a bad snapshot can never block a trade write. Returns None if both
    sides end up empty (nothing to store).
    """
    import json as _json
    items: dict[str, dict] = {}
    for _blob in (existing, new):
        if not _blob:
            continue
        try:
            for _ann in _json.loads(_blob):
                _key = _ann.get("id") or f"{_ann.get('ts')}_{_ann.get('strategy')}"
                items[_key] = _ann
        except Exception:
            logger.warning("Skipping malformed annotations_json blob during merge", exc_info=True)
    return _json.dumps(list(items.values())) if items else None

