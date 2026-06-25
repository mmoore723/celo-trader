"""
api/routes/ws.py — WebSocket endpoint for real-time bot feed.

Clients connect to /ws/live and receive JSON messages every second:
  { type: "status",  data: BotStatus }
  { type: "log",     data: { text, level, ts } }
  { type: "trade",   data: Trade }
  { type: "quote",   data: { ticker, price, change_pct } }
"""
from __future__ import annotations
import asyncio
import json
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

_ET = ZoneInfo("America/New_York")

router = APIRouter(tags=["websocket"])

_BOT_STATE_PATH = Path(__file__).resolve().parents[2] / "bot_state.json"
_LOG_PATH       = Path(__file__).resolve().parents[2] / "bot.log"

# Track connected clients
_clients: set[WebSocket] = set()


async def _broadcast(msg: dict) -> None:
    dead = set()
    for ws in _clients:
        try:
            await ws.send_json(msg)
        except Exception:
            dead.add(ws)
    _clients.difference_update(dead)


def _read_state() -> dict:
    try:
        if _BOT_STATE_PATH.exists():
            return json.loads(_BOT_STATE_PATH.read_text())
    except Exception:
        pass
    return {}


def _ts_to_et(entry: dict) -> str:
    """
    Extract a display timestamp (HH:MM AM/PM ET) from a log entry.

    The JSON logger writes:  "timestamp": "2026-06-24T00:58:44.123Z"  (UTC)
    We parse that ISO string and convert to ET so timestamps in the
    Bot Thinking panel always match the user's market session, not the
    EC2 server's UTC clock.
    """
    ts_raw = entry.get("timestamp", "")
    if ts_raw:
        try:
            # Strip trailing Z / offset so fromisoformat works on Py 3.10
            clean = ts_raw.rstrip("Z").split("+")[0]
            # The formatter appends milliseconds: "2026-06-24T00:58:44.123"
            dt_utc = datetime.fromisoformat(clean).replace(tzinfo=ZoneInfo("UTC"))
            dt_et  = dt_utc.astimezone(_ET)
            h = dt_et.hour % 12 or 12
            ampm = "AM" if dt_et.hour < 12 else "PM"
            return f"{h}:{dt_et.minute:02d}:{dt_et.second:02d} {ampm}"
        except Exception:
            pass
    # Fallback: current ET wall-clock (at least shows correct timezone)
    now_et = datetime.now(_ET)
    h = now_et.hour % 12 or 12
    ampm = "AM" if now_et.hour < 12 else "PM"
    return f"{h}:{now_et.minute:02d}:{now_et.second:02d} {ampm}"


def _tail_log(n: int = 20) -> list[dict]:
    """Return last n structured log lines from bot.log, with ET timestamps."""
    lines = []
    try:
        if not _LOG_PATH.exists():
            return []
        with open(_LOG_PATH, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            chunk = min(size, 32_768)
            f.seek(-chunk, 2)
            raw = f.read().decode("utf-8", errors="replace")
        for line in raw.splitlines()[-n:]:
            try:
                entry = json.loads(line)
            except Exception:
                entry = {"message": line, "level": "INFO"}
            entry["ts"] = _ts_to_et(entry)
            lines.append(entry)
    except Exception:
        pass
    return lines


@router.websocket("/ws/live")
async def websocket_live(ws: WebSocket) -> None:
    await ws.accept()
    _clients.add(ws)

    # Send recent log lines on connect, prefixed with a visual separator so
    # users can distinguish yesterday's session from live output.
    history = _tail_log(30)
    if history:
        await ws.send_json({"type": "log", "data": {
            "message": "── previous session ──",
            "level":   "INFO",
            "ts":      "",
            "_separator": True,
        }})
        for entry in history:
            await ws.send_json({"type": "log", "data": entry})

    last_state_hash = None
    last_log_pos    = 0

    try:
        while True:
            # 1. Bot state update
            state = _read_state()
            state_hash = json.dumps(state, sort_keys=True)
            if state_hash != last_state_hash:
                await ws.send_json({"type": "status", "data": state})
                last_state_hash = state_hash

            # 2. New log lines since last check
            try:
                if _LOG_PATH.exists():
                    with open(_LOG_PATH, "rb") as f:
                        f.seek(0, 2)
                        end = f.tell()
                        if end > last_log_pos:
                            f.seek(last_log_pos)
                            new_bytes = f.read(end - last_log_pos)
                            last_log_pos = end
                            for line in new_bytes.decode("utf-8", errors="replace").splitlines():
                                if not line.strip():
                                    continue
                                try:
                                    entry = json.loads(line)
                                except Exception:
                                    entry = {"message": line, "level": "INFO"}
                                # Always stamp ts in ET (12h) — parsed from the
                                # JSON logger's "timestamp" field (UTC ISO 8601).
                                entry["ts"] = _ts_to_et(entry)
                                await ws.send_json({"type": "log", "data": entry})
            except Exception:
                pass

            await asyncio.sleep(1)

    except WebSocketDisconnect:
        _clients.discard(ws)
    except Exception:
        _clients.discard(ws)
