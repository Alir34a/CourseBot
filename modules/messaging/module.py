"""Outbox messaging: queue now, deliver via bot loop. Filtered audience reused by any bot."""
from __future__ import annotations
import json


def queue_message(db, text: str, scope: str = "single", target_user_id: int | None = None,
                  filter_json: dict | None = None) -> int:
    from modules.database import now_iso
    cur = db.execute(
        "INSERT INTO outbox_messages(scope,filter_json,target_user_id,text,status,created_at) VALUES(?,?,?,?,?,?)",
        (scope, json.dumps(filter_json or {}, ensure_ascii=False), target_user_id, text, "pending", now_iso()),
    )
    return int(cur.lastrowid)


def audience_ids(db, filter_json: dict) -> list[int]:
    """filter_json e.g. {stage:'inactive', inactive_days:3} or {stage:'stuck_3'} or {} (all with phone)."""
    from modules.users import filter_by_stage
    if not filter_json:
        return [int(r["id"]) for r in db.fetchall("SELECT id FROM users WHERE phone IS NOT NULL")]
    stage = filter_json.get("stage", "")
    users = filter_by_stage(db, stage, int(filter_json.get("inactive_days", 0)))
    return [int(u["id"]) for u in users]


async def send_queued(db, bot, limit: int = 50) -> dict:
    """Deliver pending outbox rows. Returns {sent, failed}."""
    from modules.database import now_iso
    rows = db.fetchall("SELECT * FROM outbox_messages WHERE status='pending' ORDER BY id LIMIT ?", (limit,))
    sent = failed = 0
    for m in rows:
        try:
            targets: list[int] = []
            if m["scope"] == "single" and m["target_user_id"]:
                u = db.fetchone("SELECT telegram_id FROM users WHERE id=?", (m["target_user_id"],))
                targets = [int(u["telegram_id"])] if u else []
            else:
                import json as _j
                f = _j.loads(m["filter_json"] or "{}")
                ids = audience_ids(db, f)
                tg = db.fetchall(f"SELECT telegram_id FROM users WHERE id IN ({','.join('?'*len(ids))})", tuple(ids)) if ids else []
                targets = [int(r["telegram_id"]) for r in tg]
            for tg_id in targets:
                try:
                    await bot.send_message(chat_id=tg_id, text=m["text"])
                    sent += 1
                except Exception:
                    failed += 1
            db.execute("UPDATE outbox_messages SET status='sent', sent_at=? WHERE id=?", (now_iso(), m["id"]))
        except Exception:
            db.execute("UPDATE outbox_messages SET status='failed' WHERE id=?", (m["id"],))
            failed += 1
    return {"sent": sent, "failed": failed}
