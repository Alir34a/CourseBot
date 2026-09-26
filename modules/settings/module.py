"""Generic key-value settings (backed by the settings table). Reusable in any bot.

Convention: bot texts live under 'text:<key>' (see bot/texts.py); courses and
other modules may use their own prefixes. All values are TEXT.
"""
from __future__ import annotations
from modules.database import now_iso


def get(db, key: str, default: str | None = None) -> str | None:
    r = db.fetchone("SELECT value FROM settings WHERE key=?", (key,))
    return r["value"] if r else default


def set(db, key: str, value: str) -> None:
    db.execute("INSERT INTO settings(key,value,updated_at) VALUES(?,?,?)"
               " ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
               (key, str(value), now_iso()))


def delete(db, key: str) -> None:
    db.execute("DELETE FROM settings WHERE key=?", (key,))


def all(db) -> dict:
    return {r["key"]: r["value"] for r in db.fetchall("SELECT key, value FROM settings")}
