"""Progress + gating. ALL access checks server-side; forged callbacks cannot skip ahead.

Rules (generic):
- Episode N accessible iff all episodes < N completed (or N == 1).
- Part M of episode N accessible iff all parts < M of that episode completed AND episode N accessible.
"""
from __future__ import annotations


def completed_episode_nos(db, user_id: int, course_id: int) -> set[int]:
    """Public: episode numbers the user finished in this course."""
    rows = db.fetchall(
        """SELECT e.episode_no FROM user_episode_progress p
           JOIN episodes e ON e.id=p.episode_id
           WHERE p.user_id=? AND e.course_id=? AND p.completed_at IS NOT NULL""",
        (user_id, course_id),
    )
    return {int(r["episode_no"]) for r in rows}


_completed_episode_nos = completed_episode_nos  # backward-compat alias


def completed_part_nos(db, user_id: int, episode_id: int) -> set[int]:
    """Public: part numbers the user finished within one episode."""
    rows = db.fetchall(
        """SELECT ep.part_no FROM user_part_progress p
           JOIN episode_parts ep ON ep.id=p.part_id
           WHERE p.user_id=? AND ep.episode_id=? AND p.completed_at IS NOT NULL""",
        (user_id, episode_id),
    )
    return {int(r["part_no"]) for r in rows}


_completed_part_nos = completed_part_nos  # backward-compat alias


def unlocked_episode_no(db, user_id: int, course_slug: str) -> int:
    from modules.course_engine import get_course, list_episodes
    c = get_course(db, course_slug)
    if not c:
        return 1
    eps = list_episodes(db, course_slug)
    if not eps:
        return 1
    done = completed_episode_nos(db, user_id, c["id"])
    nxt = 1
    for ep in sorted(eps, key=lambda e: e["episode_no"]):
        if int(ep["episode_no"]) in done:
            nxt = int(ep["episode_no"]) + 1
        else:
            nxt = int(ep["episode_no"]) if nxt <= int(ep["episode_no"]) else nxt
            break
    total = max(int(e["episode_no"]) for e in eps)
    return min(nxt, total + 1)  # total+1 => course finished


def can_access_episode(db, user_id: int, course_slug: str, episode_no: int) -> bool:
    return int(episode_no) <= unlocked_episode_no(db, user_id, course_slug)


def can_access_part(db, user_id: int, course_slug: str, episode_no: int, part_no: int) -> bool:
    from modules.course_engine import get_episode, list_parts
    if not can_access_episode(db, user_id, course_slug, episode_no):
        return False
    ep = get_episode(db, course_slug, int(episode_no))
    if not ep:
        return False
    parts = list_parts(db, ep["id"])
    if not parts:
        return True
    done = completed_part_nos(db, user_id, ep["id"])
    # sequential: every part_no < requested must be completed
    return all(pn in done for pn in range(1, int(part_no)))


def start_episode(db, user_id: int, episode_id: int) -> None:
    from modules.database import now_iso
    from modules.events import EventTypes, track
    from modules.users import touch
    r = db.fetchone("SELECT * FROM user_episode_progress WHERE user_id=? AND episode_id=?", (user_id, episode_id))
    if not r:
        db.execute("INSERT INTO user_episode_progress(user_id,episode_id,started_at) VALUES(?,?,?)",
                   (user_id, episode_id, now_iso()))
        ep = db.fetchone("SELECT episode_no FROM episodes WHERE id=?", (episode_id,))
        track(db, user_id, EventTypes.EPISODE_STARTED, {"episode_id": episode_id, "episode_no": ep["episode_no"] if ep else None})
    touch(db, user_id, episode_id, None)


def start_part(db, user_id: int, part_id: int, episode_id: int) -> None:
    from modules.database import now_iso
    from modules.events import EventTypes, track
    from modules.users import touch
    if not db.fetchone("SELECT * FROM user_part_progress WHERE user_id=? AND part_id=?", (user_id, part_id)):
        db.execute("INSERT INTO user_part_progress(user_id,part_id,started_at) VALUES(?,?,?)",
                   (user_id, part_id, now_iso()))
        track(db, user_id, EventTypes.EPISODE_PART_STARTED, {"part_id": part_id, "episode_id": episode_id})
    touch(db, user_id, episode_id, part_id)


def _close_episode(db, user_id: int, course_slug: str, episode_no: int, ep: dict) -> None:
    """Mark episode completed (idempotent) + course finish check. No-op if already done."""
    from modules.course_engine import list_episodes
    from modules.database import now_iso
    from modules.events import EventTypes, track
    row = db.fetchone("SELECT completed_at FROM user_episode_progress WHERE user_id=? AND episode_id=?",
                      (user_id, ep["id"]))
    if row and row["completed_at"]:
        return
    db.execute("UPDATE user_episode_progress SET completed_at=? WHERE user_id=? AND episode_id=?",
               (now_iso(), user_id, ep["id"]))
    track(db, user_id, EventTypes.EPISODE_COMPLETED, {"episode_no": int(episode_no)})
    eps = list_episodes(db, course_slug)
    if eps and all(int(e["episode_no"]) in completed_episode_nos(db, user_id, eps[0]["course_id"]) for e in eps):
        track(db, user_id, EventTypes.COURSE_COMPLETED, {})
        if any(int(e["episode_no"]) == 15 for e in eps):
            track(db, user_id, EventTypes.EPISODE_15_COMPLETED, {})
        db.execute("UPDATE users SET status='finished' WHERE id=? AND status!='customer'", (user_id,))


def complete_episode(db, user_id: int, course_slug: str, episode_no: int) -> None:
    """Open-counts-as-seen: entering an episode with no parts completes it."""
    from modules.course_engine import get_episode
    ep = get_episode(db, course_slug, int(episode_no))
    if not ep:
        raise ValueError("episode not found")
    if not can_access_episode(db, user_id, course_slug, episode_no):
        raise PermissionError("locked")
    start_episode(db, user_id, ep["id"])
    _close_episode(db, user_id, course_slug, episode_no, ep)


def complete_part(db, user_id: int, course_slug: str, episode_no: int, part_no: int) -> dict:
    """Open-counts-as-seen: sending a part marks it complete (idempotent —
    re-views don't duplicate events). Returns status dict."""
    from modules.course_engine import get_episode, list_parts
    from modules.database import now_iso
    from modules.events import EventTypes, track
    from modules.users import touch
    ep = get_episode(db, course_slug, int(episode_no))
    if not ep:
        raise ValueError("episode not found")
    parts = list_parts(db, ep["id"])
    part = next((p for p in parts if int(p["part_no"]) == int(part_no)), None)
    if not part:
        raise ValueError("part not found")
    if not can_access_part(db, user_id, course_slug, episode_no, part_no):
        raise PermissionError("locked")
    start_episode(db, user_id, ep["id"])
    start_part(db, user_id, part["id"], ep["id"])
    row = db.fetchone("SELECT completed_at FROM user_part_progress WHERE user_id=? AND part_id=?",
                      (user_id, part["id"]))
    if not row or not row["completed_at"]:
        db.execute("UPDATE user_part_progress SET completed_at=? WHERE user_id=? AND part_id=?",
                   (now_iso(), user_id, part["id"]))
        track(db, user_id, EventTypes.EPISODE_PART_COMPLETED,
              {"episode_no": int(episode_no), "part_no": int(part_no)})
    touch(db, user_id, ep["id"], part["id"])
    total_parts = len(parts)
    done_parts = len(completed_part_nos(db, user_id, ep["id"]))
    episode_done = done_parts >= total_parts
    if episode_done:
        _close_episode(db, user_id, course_slug, episode_no, ep)
    return {"episode_completed": episode_done, "next_part_no": None if episode_done else int(part_no) + 1}


def progress_summary(db, user_id: int, course_slug: str) -> dict:
    from modules.course_engine import get_course, list_episodes
    c = get_course(db, course_slug)
    eps = list_episodes(db, course_slug)
    total = len(eps)
    done = len(completed_episode_nos(db, user_id, c["id"])) if c and eps else 0
    unlocked = unlocked_episode_no(db, user_id, course_slug)
    pct = round(done / total * 100) if total else 0
    return {"done": done, "total": total, "pct": pct, "unlocked": unlocked,
            "finished": total > 0 and done >= total}
