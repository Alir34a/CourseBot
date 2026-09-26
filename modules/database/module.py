"""Thin sqlite3 layer. All queries parameterized -> SQL-injection safe by construction."""
from __future__ import annotations
import sqlite3
from pathlib import Path
from typing import Any, Iterable

SCHEMA_PATH = Path(__file__).resolve().parents[2] / "database" / "schema.sql"
MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "database" / "migrations"
BASELINE_VERSION = 1


class Database:
    def __init__(self, path: str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON")

    def migrate(self) -> None:
        """Idempotent baseline (IF NOT EXISTS) + versioned migrations.

        Baseline schema.sql is version 1. Files database/migrations/NNN_*.sql
        apply in order; applied versions tracked in settings.schema_version.
        Safe to run on every startup.
        """
        sql = SCHEMA_PATH.read_text(encoding="utf-8")
        with self.conn:
            self.conn.executescript(sql)
            self.conn.execute(
                "INSERT INTO settings(key,value,updated_at) VALUES('schema_version','1',datetime('now'))"
                " ON CONFLICT(key) DO NOTHING")
        try:
            version = int((self.fetchone("SELECT value FROM settings WHERE key='schema_version'") or {"value": "1"})["value"])
        except (ValueError, TypeError, KeyError):
            version = BASELINE_VERSION
        if MIGRATIONS_DIR.exists():
            for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
                try:
                    num = int(path.stem.split("_")[0])
                except ValueError:
                    continue
                if num > version:
                    with self.conn:
                        self.conn.executescript(path.read_text(encoding="utf-8"))
                        self.conn.execute("UPDATE settings SET value=?, updated_at=datetime('now')"
                                          " WHERE key='schema_version'", (str(num),))
                    version = num

    def execute(self, sql: str, params: tuple | dict = ()) -> sqlite3.Cursor:
        with self.conn:
            return self.conn.execute(sql, params)

    def executemany(self, sql: str, seq: Iterable[tuple]) -> None:
        with self.conn:
            self.conn.executemany(sql, seq)

    def fetchone(self, sql: str, params: tuple | dict = ()) -> sqlite3.Row | None:
        return self.conn.execute(sql, params).fetchone()

    def fetchall(self, sql: str, params: tuple | dict = ()) -> list[sqlite3.Row]:
        return self.conn.execute(sql, params).fetchall()

    def close(self) -> None:
        try:
            self.conn.close()
        except Exception:
            pass


_db: Database | None = None


def get_db(path: str = "data/bot.db") -> Database:
    global _db
    if _db is None:
        _db = Database(path)
        _db.migrate()
    return _db


def reset_db_singleton() -> None:
    global _db
    if _db is not None:
        _db.close()
    _db = None


def now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
