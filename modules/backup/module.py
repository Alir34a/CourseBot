"""Offline SQLite backup/restore. Generic: works for any bot using a sqlite file.

Safety: backup uses the sqlite online-backup API (consistent even while the
bot runs). Restore REPLACES the live DB file, so the bot and admin panel
must be stopped first — restore_to() enforces this with require_stopped().
CLI: python -m modules.backup backup | restore <file> | list
"""
from __future__ import annotations
import shutil
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path


def backup_dir_for(db_path: str) -> Path:
    d = Path(db_path).parent / "backups"
    d.mkdir(parents=True, exist_ok=True)
    return d


def backup(db_path: str, dest_dir: str | None = None) -> str:
    """Consistent snapshot via sqlite backup API. Returns snapshot file path."""
    src = Path(db_path)
    if not src.exists():
        raise FileNotFoundError(f"database not found: {db_path}")
    out_dir = Path(dest_dir) if dest_dir else backup_dir_for(db_path)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest = out_dir / f"bot-{stamp}.db"
    # NOTE: sqlite3.Connection as a context manager does NOT close the
    # handle — closing explicitly so Windows file locks are released.
    src_conn = sqlite3.connect(str(src))
    try:
        dst_conn = sqlite3.connect(str(dest))
        try:
            src_conn.backup(dst_conn)
        finally:
            dst_conn.close()
    finally:
        src_conn.close()
    return str(dest)


def list_backups(db_path: str) -> list[str]:
    d = backup_dir_for(db_path)
    return sorted(str(p) for p in d.glob("bot-*.db"))


def restore_to(snapshot: str, db_path: str, require_stopped: bool = True) -> str:
    """Replace live DB with snapshot. require_stopped=True forces the caller to
    confirm the bot/panel are down (pass require_stopped=False only from tests)."""
    if require_stopped:
        raise RuntimeError(
            "Stop the bot (bot.main) and admin panel before restore, "
            "then call restore_to(..., require_stopped=False).")
    snap = Path(snapshot)
    if not snap.exists():
        raise FileNotFoundError(f"snapshot not found: {snapshot}")
    chk = sqlite3.connect(str(snap))
    try:
        chk.execute("PRAGMA integrity_check").fetchall()
    finally:
        chk.close()
    live = Path(db_path)
    pre = live.with_suffix(".db.pre-restore")
    last_err: Exception | None = None
    for _ in range(10):  # Windows AV/indexer may briefly hold the file
        try:
            if live.exists():
                live.replace(pre)
            shutil.copyfile(str(snap), str(live))
            return str(live)
        except PermissionError as e:
            last_err = e
            time.sleep(0.2)
    raise last_err  # type: ignore[misc]
