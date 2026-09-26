"""Generic course/episode/part engine. Works for 15, 30 or 50 episodes without logic change."""
from __future__ import annotations
import json


def ensure_course(db, slug: str, title: str, description: str = "") -> dict:
    db.execute(
        "INSERT INTO courses(slug,title,description,is_active) VALUES(?,?,?,1)"
        " ON CONFLICT(slug) DO UPDATE SET title=excluded.title",
        (slug, title, description),
    )
    return dict(db.fetchone("SELECT * FROM courses WHERE slug=?", (slug,)))


def get_course(db, slug: str) -> dict | None:
    r = db.fetchone("SELECT * FROM courses WHERE slug=?", (slug,))
    return dict(r) if r else None


def list_episodes(db, course_slug: str, only_active: bool = True) -> list[dict]:
    c = get_course(db, course_slug)
    if not c:
        return []
    q = "SELECT * FROM episodes WHERE course_id=? " + ("AND is_active=1 " if only_active else "") + "ORDER BY sort_order, episode_no"
    return [dict(r) for r in db.fetchall(q, (c["id"],))]


def get_episode(db, course_slug: str, episode_no: int) -> dict | None:
    c = get_course(db, course_slug)
    if not c:
        return None
    r = db.fetchone("SELECT * FROM episodes WHERE course_id=? AND episode_no=?", (c["id"], int(episode_no)))
    return dict(r) if r else None


def list_parts(db, episode_id: int, only_active: bool = True) -> list[dict]:
    q = "SELECT * FROM episode_parts WHERE episode_id=? " + ("AND is_active=1 " if only_active else "") + "ORDER BY sort_order, part_no"
    return [dict(r) for r in db.fetchall(q, (episode_id,))]


def get_part(db, episode_id: int, part_no: int) -> dict | None:
    r = db.fetchone("SELECT * FROM episode_parts WHERE episode_id=? AND part_no=?", (episode_id, int(part_no)))
    return dict(r) if r else None


def upsert_episode(db, course_slug: str, episode_no: int, title: str, caption: str = "", is_active: int = 1) -> dict:
    c = get_course(db, course_slug)
    if not c:
        raise ValueError("course not found")
    db.execute(
        """INSERT INTO episodes(course_id,episode_no,title,caption,is_active,sort_order)
           VALUES(?,?,?,?,?,?) ON CONFLICT(course_id,episode_no)
           DO UPDATE SET title=excluded.title, caption=excluded.caption, is_active=excluded.is_active""",
        (c["id"], int(episode_no), title, caption, is_active, int(episode_no)),
    )
    return get_episode(db, course_slug, int(episode_no))


def upsert_part(db, episode_id: int, part_no: int, kind: str = "text", text: str = "", file_id: str | None = None) -> dict:
    db.execute(
        """INSERT INTO episode_parts(episode_id,part_no,kind,file_id,text,sort_order,is_active)
           VALUES(?,?,?,?,?,?,1) ON CONFLICT(episode_id,part_no)
           DO UPDATE SET kind=excluded.kind, file_id=excluded.file_id, text=excluded.text""",
        (episode_id, int(part_no), kind, file_id, text, int(part_no)),
    )
    return dict(db.fetchone("SELECT * FROM episode_parts WHERE episode_id=? AND part_no=?", (episode_id, int(part_no))))


def seed_from_json(db, course_slug: str, data: dict) -> dict:
    """data: {title, description, episodes:[{no,title,caption,parts:[{no,kind,text,file_id}]}]}"""
    ensure_course(db, course_slug, data.get("title", course_slug), data.get("description", ""))
    n_ep = n_part = 0
    for ep in data.get("episodes", []):
        e = upsert_episode(db, course_slug, ep["no"], ep.get("title", f"اپیزود {ep['no']}"), ep.get("caption", ""))
        n_ep += 1
        for p in ep.get("parts", [{"no": 1, "kind": "text", "text": ep.get("caption", "")}]):
            upsert_part(db, e["id"], p["no"], p.get("kind", "text"), p.get("text", ""), p.get("file_id"))
            n_part += 1
    return {"episodes": n_ep, "parts": n_part}


def get_course_by_id(db, course_id: int) -> dict | None:
    r = db.fetchone("SELECT * FROM courses WHERE id=?", (course_id,))
    return dict(r) if r else None


def list_courses(db, only_active: bool = False) -> list[dict]:
    q = "SELECT * FROM courses " + ("WHERE is_active=1 " if only_active else "") + "ORDER BY id"
    return [dict(r) for r in db.fetchall(q)]


def create_course(db, slug: str, title: str, description: str = "") -> dict:
    import re
    slug = (slug or "").strip()
    if not re.match(r"^[a-z0-9][a-z0-9_-]{1,60}$", slug):
        raise ValueError("bad slug")
    if not title or len(title) > 200:
        raise ValueError("bad title")
    db.execute("INSERT INTO courses(slug,title,description,is_active) VALUES(?,?,?,1)",
               (slug, title.strip(), (description or "")[:2000]))
    return dict(db.fetchone("SELECT * FROM courses WHERE slug=?", (slug,)))


def set_course_active(db, course_id: int, active: bool) -> None:
    db.execute("UPDATE courses SET is_active=? WHERE id=?", (1 if active else 0, course_id))


def delete_course(db, course_id: int) -> dict:
    """Delete course + episodes/parts/progress via FK cascade. Returns counts removed.
    Detaches users (current_course -> NULL) and offers (course-specific -> global)
    FIRST, otherwise FK enforcement blocks the delete."""
    eps = db.fetchall("SELECT id FROM episodes WHERE course_id=?", (course_id,))
    n_ep = len(eps)
    n_part = 0
    if eps:
        ids = ",".join("?" * len(eps))
        r = db.fetchone(f"SELECT COUNT(*) c FROM episode_parts WHERE episode_id IN ({ids})",
                        tuple(e["id"] for e in eps))
        n_part = int(r["c"])
    db.execute("UPDATE users SET current_course_id=NULL WHERE current_course_id=?", (course_id,))
    db.execute("UPDATE offers SET course_id=NULL WHERE course_id=?", (course_id,))
    db.execute("DELETE FROM episodes WHERE course_id=?", (course_id,))
    db.execute("DELETE FROM courses WHERE id=?", (course_id,))
    return {"episodes": n_ep, "parts": n_part}


def delete_episode(db, episode_id: int) -> None:
    db.execute("DELETE FROM episodes WHERE id=?", (episode_id,))  # parts+progress cascade


def delete_part(db, episode_id: int, part_no: int) -> bool:
    cur = db.execute("DELETE FROM episode_parts WHERE episode_id=? AND part_no=?", (episode_id, int(part_no)))
    return cur.rowcount > 0

def course_stats(db, course_id: int) -> dict:
    n_ep = db.fetchone("SELECT COUNT(*) c FROM episodes WHERE course_id=? AND is_active=1", (course_id,))["c"]
    r = db.fetchone("SELECT COUNT(*) c FROM user_episode_progress p JOIN episodes e ON e.id=p.episode_id "
                    "WHERE e.course_id=?", (course_id,))
    return {"episodes": int(n_ep), "starters": int(r["c"])}


def auto_slug(db) -> str:
    """Next free course slug (course-1, course-2, ...). No manual slugs needed."""
    n = 1
    existing = {r["slug"] for r in db.fetchall("SELECT slug FROM courses")}
    while f"course-{n}" in existing:
        n += 1
    return f"course-{n}"


def next_episode_no(db, course_slug: str) -> int:
    r = db.fetchone("SELECT MAX(episode_no) m FROM episodes WHERE course_id="
                    "(SELECT id FROM courses WHERE slug=?)", (course_slug,))
    return int(r["m"] or 0) + 1


def next_part_no(db, episode_id: int) -> int:
    r = db.fetchone("SELECT MAX(part_no) m FROM episode_parts WHERE episode_id=?", (episode_id,))
    return int(r["m"] or 0) + 1


def set_episode_media(db, episode_id: int, kind: str | None, file_id: str | None) -> None:
    """Episode's own media (photo/video/... shown at entry + review header).
    Stored in cover_* columns (legacy name, internal only)."""
    db.execute("UPDATE episodes SET cover_kind=?, cover_file_id=? WHERE id=?", (kind, file_id, episode_id))


def update_part_content(db, episode_id: int, part_no: int, kind: str, text: str,
                        file_id: str | None) -> bool:
    cur = db.execute("UPDATE episode_parts SET kind=?, text=?, file_id=? WHERE episode_id=? AND part_no=?",
                     (kind, text, file_id, episode_id, int(part_no)))
    return cur.rowcount > 0
