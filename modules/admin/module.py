"""Admin service: dashboard aggregates + user detail over reusable modules.

Auth note: the Telegram console authenticates via ADMIN_IDS (Telegram itself);
no passwords live here. Generic across bots.
"""
from __future__ import annotations


def dashboard(db, course_slug: str) -> dict:
    from modules.analytics import dashboard_stats
    return dashboard_stats(db, course_slug)


def user_detail(db, user_id: int) -> dict | None:
    from modules.events import user_timeline
    u = db.fetchone("SELECT * FROM users WHERE id=?", (user_id,))
    if not u:
        return None
    out = dict(u)
    out["timeline"] = user_timeline(db, user_id, 200)
    out["episodes"] = [dict(r) for r in db.fetchall(
        """SELECT c.title AS course_title, e.episode_no, e.title, p.started_at, p.completed_at
           FROM user_episode_progress p
           JOIN episodes e ON e.id=p.episode_id
           JOIN courses c ON c.id=e.course_id
           WHERE p.user_id=? ORDER BY c.title, e.episode_no""", (user_id,))]
    return out
