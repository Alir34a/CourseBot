"""Configurable purchase offer + sales-webhook hook for external shops."""
from __future__ import annotations


def get_active_offer(db, course_id: int | None = None) -> dict | None:
    """Latest active offer: prefer the course's own, fall back to global (course_id NULL)."""
    if course_id is None:
        r = db.fetchone("SELECT * FROM offers WHERE is_active=1 ORDER BY id DESC LIMIT 1")
    else:
        r = db.fetchone(
            """SELECT * FROM offers WHERE is_active=1 AND (course_id=? OR course_id IS NULL)
               ORDER BY (course_id IS NULL), id DESC LIMIT 1""", (course_id,))
    return dict(r) if r else None


def should_show_offer(db, user_id: int, course_slug: str, trigger_rule: str) -> bool:
    """trigger_rule e.g. 'episode:15' (after completing ep15) or 'episode:5' or 'always'."""
    from modules.progress import progress_summary
    if trigger_rule.strip() == "always":
        return True
    kind, _, val = trigger_rule.partition(":")
    if kind == "episode":
        s = progress_summary(db, user_id, course_slug)
        return s["done"] >= int(val or 0)
    return False


def log_interaction(db, user_id: int, offer_id: int, kind: str, meta: dict | None = None) -> None:
    from modules.database import now_iso
    from modules.events import EventTypes, track
    import json
    db.execute("INSERT INTO offer_interactions(user_id,offer_id,kind,created_at,meta) VALUES(?,?,?,?,?)",
               (user_id, offer_id, kind, now_iso(), json.dumps(meta or {}, ensure_ascii=False)))
    mapping = {"viewed": EventTypes.PURCHASE_OFFER_VIEWED, "clicked": EventTypes.PURCHASE_OFFER_CLICKED,
               "started": EventTypes.PURCHASE_STARTED, "completed": EventTypes.PURCHASE_COMPLETED}
    if kind in mapping:
        track(db, user_id, mapping[kind], {"offer_id": offer_id})


def record_purchase(db, user_id: int, offer_id: int | None, amount: int | None = None,
                    external_ref: str | None = None, secret: str | None = None,
                    expected_secret: str = "") -> dict:
    """External webhook path MUST pass the shared secret; direct bot clicks use amount=None flow."""
    from modules.database import now_iso
    from modules.events import EventTypes, track
    if expected_secret and secret != expected_secret:
        raise PermissionError("bad webhook secret")
    cur = db.execute("INSERT INTO purchases(user_id,offer_id,amount,status,external_ref,created_at) VALUES(?,?,?,?,?,?)",
                     (user_id, offer_id, amount, "completed", external_ref, now_iso()))
    db.execute("UPDATE users SET status='customer' WHERE id=?", (user_id,))
    track(db, user_id, EventTypes.PURCHASE_COMPLETED, {"offer_id": offer_id, "amount": amount})
    return dict(db.fetchone("SELECT * FROM purchases WHERE id=?", (cur.lastrowid,)))


def request_purchase(db, user_id: int, offer_id: int | None) -> dict:
    """User tapped 'I paid': create a pending request (deduped) for admin approval."""
    from modules.database import now_iso
    from modules.events import EventTypes, track
    row = db.fetchone("SELECT * FROM purchases WHERE user_id=? AND status='pending' ORDER BY id DESC LIMIT 1",
                      (user_id,))
    if row:
        return dict(row)
    cur = db.execute("INSERT INTO purchases(user_id,offer_id,amount,status,external_ref,created_at) VALUES(?,?,?, ?,?,?)",
                     (user_id, offer_id, None, "pending", None, now_iso()))
    track(db, user_id, EventTypes.PURCHASE_STARTED, {"offer_id": offer_id})
    log_interaction(db, user_id, offer_id, "started") if offer_id else None
    return dict(db.fetchone("SELECT * FROM purchases WHERE id=?", (cur.lastrowid,)))


def pending_purchases(db, limit: int = 20) -> list[dict]:
    return [dict(r) for r in db.fetchall(
        """SELECT p.*, u.full_name, u.phone, u.telegram_id, o.title AS offer_title, o.slug AS offer_slug
           FROM purchases p JOIN users u ON u.id=p.user_id
           LEFT JOIN offers o ON o.id=p.offer_id
           WHERE p.status='pending' ORDER BY p.id DESC LIMIT ?""", (limit,))]


def purchase_history(db, limit: int = 20) -> list[dict]:
    return [dict(r) for r in db.fetchall(
        """SELECT p.*, u.full_name, u.phone, u.telegram_id, o.title AS offer_title
           FROM purchases p JOIN users u ON u.id=p.user_id
           LEFT JOIN offers o ON o.id=p.offer_id
           WHERE p.status!='pending' ORDER BY p.id DESC LIMIT ?""", (limit,))]


def approve_purchase(db, purchase_id: int) -> dict | None:
    from modules.database import now_iso
    from modules.events import EventTypes, track
    p = db.fetchone("SELECT * FROM purchases WHERE id=? AND status='pending'", (purchase_id,))
    if not p:
        return None
    db.execute("UPDATE purchases SET status='completed' WHERE id=?", (purchase_id,))
    db.execute("UPDATE users SET status='customer' WHERE id=?", (p["user_id"],))
    track(db, p["user_id"], EventTypes.PURCHASE_COMPLETED, {"offer_id": p["offer_id"]})
    return dict(db.fetchone("SELECT * FROM purchases WHERE id=?", (purchase_id,)))


def decline_purchase(db, purchase_id: int) -> dict | None:
    from modules.events import EventTypes, track
    p = db.fetchone("SELECT * FROM purchases WHERE id=? AND status='pending'", (purchase_id,))
    if not p:
        return None
    db.execute("UPDATE purchases SET status='declined' WHERE id=?", (purchase_id,))
    track(db, p["user_id"], EventTypes.PURCHASE_DECLINED, {"offer_id": p["offer_id"]})
    return dict(db.fetchone("SELECT * FROM purchases WHERE id=?", (purchase_id,)))


def upsert_offer(db, slug: str, title: str, text: str, url: str, button_text: str = "خرید",
                 trigger_rule: str = "episode:15", is_active: int = 1,
                 media_kind: str | None = None, media_ref: str | None = None,
                 course_id: int | None = None) -> dict:
    db.execute(
        """INSERT INTO offers(slug,title,text,media_kind,media_ref,url,button_text,trigger_rule,is_active,course_id)
           VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(slug)
           DO UPDATE SET title=excluded.title,text=excluded.text,url=excluded.url,
                         button_text=excluded.button_text,trigger_rule=excluded.trigger_rule,
                         is_active=excluded.is_active,media_kind=excluded.media_kind,media_ref=excluded.media_ref,
                         course_id=excluded.course_id""",
        (slug, title, text, media_kind, media_ref, url, button_text, trigger_rule, is_active, course_id),
    )
    return dict(db.fetchone("SELECT * FROM offers WHERE slug=?", (slug,)))


def list_offers(db, course_id: int | None = None) -> list[dict]:
    if course_id is None:
        return [dict(r) for r in db.fetchall("SELECT * FROM offers ORDER BY id DESC")]
    return [dict(r) for r in db.fetchall(
        "SELECT * FROM offers WHERE course_id=? OR course_id IS NULL ORDER BY id DESC", (course_id,))]


def delete_offer(db, offer_id: int) -> None:
    db.execute("DELETE FROM offer_interactions WHERE offer_id=?", (offer_id,))
    db.execute("DELETE FROM offers WHERE id=?", (offer_id,))
