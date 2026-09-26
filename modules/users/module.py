"""User lifecycle. Depends on database+events only (generic, no course texts)."""
from __future__ import annotations


def get_or_create(db, telegram_id: int, username: str | None = None) -> dict:
    from modules.database import now_iso
    from modules.events import EventTypes, track
    row = db.fetchone("SELECT * FROM users WHERE telegram_id=?", (int(telegram_id),))
    if row:
        db.execute(
            "UPDATE users SET username=?, last_activity_at=? WHERE telegram_id=?",
            (username, now_iso(), int(telegram_id)),
        )
        return dict(db.fetchone("SELECT * FROM users WHERE telegram_id=?", (int(telegram_id),)))
    now = now_iso()
    cur = db.execute(
        "INSERT INTO users(telegram_id,username,status,created_at,last_activity_at) VALUES(?,?,?,?,?)",
        (int(telegram_id), username, "new", now, now),
    )
    user = dict(db.fetchone("SELECT * FROM users WHERE id=?", (cur.lastrowid,)))
    track(db, user["id"], EventTypes.USER_REGISTERED, {"telegram_id": int(telegram_id)})
    return user


def get_by_telegram(db, telegram_id: int) -> dict | None:
    r = db.fetchone("SELECT * FROM users WHERE telegram_id=?", (int(telegram_id),))
    return dict(r) if r else None


def get_by_id(db, user_id: int) -> dict | None:
    r = db.fetchone("SELECT * FROM users WHERE id=?", (user_id,))
    return dict(r) if r else None


def set_phone(db, user_id: int, phone: str) -> dict:
    from modules.database import now_iso
    from modules.events import EventTypes, track
    now = now_iso()
    db.execute(
        "UPDATE users SET phone=?, status='phone_submitted', phone_registered_at=?, last_activity_at=? WHERE id=?",
        (phone, now, now, user_id),
    )
    track(db, user_id, EventTypes.PHONE_SUBMITTED, {})
    return dict(db.fetchone("SELECT * FROM users WHERE id=?", (user_id,)))


def set_name(db, user_id: int, full_name: str) -> dict:
    from modules.database import now_iso
    from modules.events import EventTypes, track
    db.execute(
        "UPDATE users SET full_name=?, status='in_course', last_activity_at=? WHERE id=?",
        (full_name.strip()[:120], now_iso(), user_id),
    )
    track(db, user_id, EventTypes.NAME_SUBMITTED, {"name": full_name.strip()[:120]})
    return dict(db.fetchone("SELECT * FROM users WHERE id=?", (user_id,)))


def touch(db, user_id: int, last_episode_id: int | None = None, last_part_id: int | None = None) -> None:
    from modules.database import now_iso
    if last_episode_id is None:
        db.execute("UPDATE users SET last_activity_at=? WHERE id=?", (now_iso(), user_id))
    else:
        db.execute(
            "UPDATE users SET last_activity_at=?, last_episode_id=?, last_part_id=? WHERE id=?",
            (now_iso(), last_episode_id, last_part_id, user_id),
        )


def search(db, q: str, limit: int = 50) -> list[dict]:
    like = f"%{q}%"
    return [dict(r) for r in db.fetchall(
        "SELECT * FROM users WHERE full_name LIKE ? OR username LIKE ? OR phone LIKE ? OR CAST(telegram_id AS TEXT) LIKE ? LIMIT ?",
        (like, like, like, like, limit))]


def filter_by_stage(db, stage: str, inactive_days: int = 0, course_slug: str | None = None) -> list[dict]:
    """stage: registered_only|not_started|stuck_N|reached_N|finished|offer_viewed|offer_clicked|customers|inactive

    Note: stuck_N/reached_N resolve the course via settings.course_slug, so the
    same code works for any course slug (set per bot in settings/.env)."""
    from datetime import datetime, timezone, timedelta
    if stage == "registered_only":
        return [dict(r) for r in db.fetchall("SELECT * FROM users WHERE status='phone_submitted'")]
    if stage == "not_started":
        return [dict(r) for r in db.fetchall(
            "SELECT u.* FROM users u LEFT JOIN user_episode_progress p ON p.user_id=u.id WHERE p.id IS NULL AND u.phone IS NOT NULL")]
    if stage.startswith("stuck_") or stage.startswith("reached_"):
        n = int(stage.split("_")[1])
        slug = course_slug or (db.fetchone("SELECT value FROM settings WHERE key='course_slug'" ) or {"value": ""})["value"]
        return [dict(r) for r in db.fetchall(
            """SELECT u.* FROM users u JOIN episodes e ON e.id=u.last_episode_id
               JOIN courses c ON c.id=e.course_id
               WHERE e.episode_no=? AND c.slug=?""",
            (n, slug,))]
    if stage == "finished":
        return [dict(r) for r in db.fetchall("SELECT * FROM users WHERE status IN ('finished','customer')")]
    if stage == "customers":
        return [dict(r) for r in db.fetchall("SELECT u.* FROM users u JOIN purchases p ON p.user_id=u.id WHERE p.status='completed'")]
    if stage == "inactive" and inactive_days > 0:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=inactive_days)).isoformat()
        return [dict(r) for r in db.fetchall("SELECT * FROM users WHERE last_activity_at < ?", (cutoff,))]
    if stage in ("offer_viewed", "offer_clicked"):
        kind = "viewed" if stage == "offer_viewed" else "clicked"
        return [dict(r) for r in db.fetchall(
            "SELECT DISTINCT u.* FROM users u JOIN offer_interactions o ON o.user_id=u.id WHERE o.kind=?", (kind,))]
    return []
