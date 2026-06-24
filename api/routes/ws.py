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
from pathlib import Path

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

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


def _tail_log(n: int = 20) -> list[dict]:
    """Return last n structured log lines from bot.log."""
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
                lines.append(json.loads(line))
            except Exception:
                lines.append({"message": line, "level": "INFO"})
    except Exception:
        pass
    return lines


@router.websocket("/ws/live")
async def websocket_live(ws: WebSocket) -> None:
    await ws.accept()
    _clients.add(ws)

    # Send recent log lines on connect
    for entry in _tail_log(30):
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
                                    entry = {"message": line, "level": "INFO",
                                             "ts": time.strftime("%H:%M:%S")}
                                await ws.send_json({"type": "log", "data": entry})
            except Exception:
                pass

            await asyncio.sleep(1)

    except WebSocketDisconnect:
        _clients.discard(ws)
    except Exception:
        _clients.discard(ws)
