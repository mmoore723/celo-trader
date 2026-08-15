"""Append-only audit history for reviewed strategy switch changes."""
from __future__ import annotations

from database.connection import get_conn
from database.helpers import _now_et


def record_strategy_setting_changes(
    actor_user_id: str,
    changes: list[tuple[str, str, bool, bool]],
) -> None:
    """Record effective switch changes after a successful settings save."""
    if not changes:
        return
    timestamp = _now_et().isoformat()
    with get_conn() as conn:
        conn.executemany(
            """
            INSERT INTO strategy_setting_changes
                (changed_at, actor_user_id, strategy_id, setting_key,
                 previous_enabled, new_enabled)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (timestamp, actor_user_id, strategy_id, setting_key, int(before), int(after))
                for strategy_id, setting_key, before, after in changes
            ],
        )


def get_strategy_setting_changes(limit: int = 50) -> list[dict]:
    """Return newest-first changes from this account's active database."""
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT changed_at, actor_user_id, strategy_id, setting_key,
                   previous_enabled, new_enabled
            FROM strategy_setting_changes
            ORDER BY id DESC LIMIT ?
            """,
            (max(1, min(int(limit), 250)),),
        ).fetchall()
    return [
        {
            **dict(row),
            "previous_enabled": bool(row["previous_enabled"]),
            "new_enabled": bool(row["new_enabled"]),
        }
        for row in rows
    ]
