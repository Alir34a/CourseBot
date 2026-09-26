"""Inactive-user reminders built on messaging + users filters.

NOTE for reuse: pass an explicit `template` for every new bot. The built-in
default text is this project's Persian copy, kept only as a fallback.
"""
from __future__ import annotations


def inactive_users(db, days: int) -> list[dict]:
    from modules.users import filter_by_stage
    return filter_by_stage(db, "inactive", days)


def reminder_text(full_name: str | None, last_episode_no: int | None, template: str | None = None) -> str:
    if template:
        return template.format(name=full_name or "دوست عزیز", episode=last_episode_no or 1)
    return (f"{full_name or 'دوست عزیز'} 🌱\n"
            f"مدتیه ادامه ندادی؛ الان وقتشه برگردی و از اپیزود {last_episode_no or 1} ادامه بدی.")


def queue_reminders(db, days: int = 3, template: str | None = None, limit: int = 200) -> int:
    from modules.messaging import queue_message
    users = inactive_users(db, days)[:limit]
    n = 0
    for u in users:
        last_no = None
        if u.get("last_episode_id"):
            ep = db.fetchone("SELECT episode_no FROM episodes WHERE id=?", (u["last_episode_id"],))
            last_no = int(ep["episode_no"]) if ep else None
        queue_message(db, reminder_text(u.get("full_name"), last_no, template),
                      scope="single", target_user_id=int(u["id"]))
        n += 1
    return n
