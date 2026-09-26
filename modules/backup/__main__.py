"""CLI: python -m modules.backup backup | restore <snapshot> [--i-stopped-the-bot] | list"""
import os
import sys

from modules.backup import backup, list_backups, restore_to
from modules.config import load_config

cfg = load_config()
cmd = sys.argv[1] if len(sys.argv) > 1 else "backup"
if cmd == "backup":
    print(backup(cfg.database_path))
elif cmd == "list":
    print("\n".join(list_backups(cfg.database_path)) or "(no backups)")
elif cmd == "restore" and len(sys.argv) > 2:
    stopped = "--i-stopped-the-bot" in sys.argv
    print(restore_to(sys.argv[2], cfg.database_path, require_stopped=not stopped))
else:
    print(__doc__)
    sys.exit(2)
