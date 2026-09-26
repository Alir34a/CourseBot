"""Append-only generic event tracking. New types need no core change.

Resilience contract: track() NEVER breaks the caller's main flow. If the
events store fails, the failure is logged and track() returns 0 so the bot
can continue serving the user (analytics gap is preferable to a dead bot).
Use track_strict() in tests/migrations when you want failures to raise.
"""
from __future__ import annotations
import json


class EventTypes:
    USER_REGISTERED = "user_registered"
    PHONE_SUBMITTED = "phone_submitted"
    NAME_SUBMITTED = "name_submitted"
    EPISODE_STARTED = "episode_started"
    EPISODE_PART_STARTED = "episode_part_started"
    EPISODE_PART_COMPLETED = "episode_part_completed"
    EPISODE_COMPLETED = "episode_completed"
    # Legacy alias kept for backward compatibility: emitted only when the
    # finished course actually contains an episode numbered 15. New code
    # should rely on COURSE_COMPLETED (generic, any course length).
    EPISODE_15_COMPLETED = "episode_15_completed"
    COURSE_COMPLETED = "course_completed"
    PURCHASE_OFFER_VIEWED = "purchase_offer_viewed"
    PURCHASE_OFFER_CLICKED = "purchase_offer_clicked"
    PURCHASE_STARTED = "purchase_started"
    PURCHASE_COMPLETED = "purchase_completed"
    PURCHASE_DECLINED = "purchase_declined"
    USER_INACTIVE = "user_inactive"


def track_strict(db, user_id: int | None, type: str, payload: dict | None = None) -> int:
    """Insert an event; raises on DB failure. Row: (user_id, type, payload JSON, UTC ts)."""
    from modules.database import now_iso
    cur = db.execute(
        "INSERT INTO events(user_id,type,payload,created_at) VALUES(?,?,?,?)",
        (user_id, type, json.dumps(payload or {}, ensure_ascii=False), now_iso()),
    )
    return int(cur.lastrowid)


def track(db, user_id: int | None, type: str, payload: dict | None = None) -> int:
    """Resilient wrapper around track_strict(): logs and returns 0 on failure."""
    try:
        return track_strict(db, user_id, type, payload)
    except Exception as exc:  # never break the user flow for analytics
        try:
            from modules.logging_mod import get_logger
            get_logger("events").warning("event dropped (%s): %s", type, exc)
        except Exception:
            pass
        return 0


def user_timeline(db, user_id: int, limit: int = 100) -> list[dict]:
    rows = db.fetchall(
        "SELECT id,type,payload,created_at FROM events WHERE user_id=? ORDER BY id DESC LIMIT ?",
        (user_id, limit),
    )
    return [dict(r) for r in rows]


def count_by_type(db, type: str, since: str | None = None) -> int:
    if since:
        r = db.fetchone("SELECT COUNT(*) c FROM events WHERE type=? AND created_at>=?", (type, since))
    else:
        r = db.fetchone("SELECT COUNT(*) c FROM events WHERE type=?", (type,))
    return int(r["c"]) if r else 0
