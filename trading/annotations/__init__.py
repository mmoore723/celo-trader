"""
trading/annotations/ — Real-time chart annotation emitter.

Writes bot-detected patterns (FVG zones, BOS levels, signal markers, veto markers)
to this user's state["chart_annotations"][ticker] (see trading/state.py::
get_user_state) so the frontend can overlay them on the price chart as the
trading day progresses.

Annotation types:
  "hline"  — horizontal price line (BOS level, TREND_CONT swing level, OR mid)
  "zone"   — shaded price band (FVG gap, IFVG inverted zone)
  "marker" — candle-pinned marker (signal fired, veto, Stage 1 hit)

Split out of the old single trading/annotations.py (2026-08-01, file-size
cleanup) into:
  - constants.py: _MAX_ANNOTATIONS, _COLORS
  - emit.py:      emit_annotation(), emit_signal_annotation()
  - snapshot.py:  clear_annotations(), snapshot_annotations()

No monkeypatching of this module's names was found anywhere in the codebase
(grep-verified), so this __init__.py just re-exports normally.
"""
from __future__ import annotations

from trading.annotations.constants import _MAX_ANNOTATIONS, _COLORS
from trading.annotations.emit import emit_annotation, emit_signal_annotation
from trading.annotations.snapshot import clear_annotations, snapshot_annotations

__all__ = [
    "emit_annotation",
    "emit_signal_annotation",
    "clear_annotations",
    "snapshot_annotations",
]
