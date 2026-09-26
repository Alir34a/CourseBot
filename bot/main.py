"""Bot entrypoint. Wires config + db + seed + PTB handlers. Run: python -m bot.main"""
from __future__ import annotations
import asyncio
import json
from pathlib import Path
from telegram.ext import CallbackQueryHandler, CommandHandler, MessageHandler, filters

from modules.config import load_config
from modules.course_engine import seed_from_json
from modules.database import Database
from modules.logging_mod import get_logger
from modules.offers import upsert_offer
from modules.telegram_core import build_app

log = get_logger("main")


def seed_all(db: Database, cfg) -> None:
    """First-run sample data ONLY. Never touches an existing database, so admin
    edits from /admin are never overwritten by a restart."""
    if db.fetchone("SELECT id FROM courses LIMIT 1"):
        return
    root = Path(__file__).resolve().parents[1]
    ep_path = root / "content" / "seed_episodes.json"
    if ep_path.exists():
        data = json.loads(ep_path.read_text(encoding="utf-8"))
        res = seed_from_json(db, data.get("course_slug", cfg.course_slug), data)
        log.info(f"seeded episodes: {res}")
        db.execute("INSERT INTO settings(key,value,updated_at) VALUES('course_slug',?,datetime('now'))"
                   " ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                   (data.get("course_slug", cfg.course_slug),))
    off_path = root / "content" / "seed_offer.json"
    if off_path.exists():
        o = json.loads(off_path.read_text(encoding="utf-8"))
        upsert_offer(db, o["offer_slug"], o["title"], o["text"], o.get("url") or cfg.offer_url,
                     o.get("button_text", "خرید"), o.get("trigger_rule", cfg.offer_trigger))
        log.info("seeded offer")


OUTBOX_INTERVAL = 30  # seconds between outbox delivery passes


async def _outbox_loop(app) -> None:
    """Background delivery for admin-panel queued messages. Runs until shutdown."""
    from modules.messaging import send_queued
    await asyncio.sleep(5)  # let polling settle first
    while True:
        try:
            res = await send_queued(app.bot_data["db"], app.bot)
            if res["sent"] or res["failed"]:
                log.info("outbox pass: %s", res)
        except Exception:
            log.exception("outbox pass failed")
        await asyncio.sleep(OUTBOX_INTERVAL)


async def _post_init(app) -> None:
    asyncio.create_task(_outbox_loop(app))


def main() -> None:
    from bot.admin_handlers import admin_consume_media, cmd_admin, on_admin_callback
    from bot.handlers import cmd_episodes, cmd_help, cmd_start, on_callback, on_contact, on_text
    from modules.config import is_owner_configured
    cfg = load_config()
    missing = [k for k, ok in is_owner_configured(cfg).items() if not ok]
    if missing:
        log.error(
            "Owner configuration missing: %s. "
            "Windows: copy config\\.env.example .env , then fill BOT_TOKEN, ADMIN_IDS, OWNER_EMAIL in .env "
            "and rerun. Get token from @BotFather, numeric ID from @userinfobot.",
            ", ".join(missing))
        raise SystemExit(2)
    db = Database(cfg.database_path)
    db.migrate()
    seed_all(db, cfg)
    app = build_app(cfg.bot_token, post_init=_post_init)
    app.bot_data["db"] = db
    app.bot_data["cfg"] = cfg
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("episodes", cmd_episodes))
    app.add_handler(CommandHandler("admin", cmd_admin))
    app.add_handler(MessageHandler(filters.CONTACT, on_contact))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.add_handler(MessageHandler(filters.ATTACHMENT, admin_consume_media))
    app.add_handler(CallbackQueryHandler(on_admin_callback, pattern=r"^adm:"))
    app.add_handler(CallbackQueryHandler(on_callback))
    log.info("bot polling started")
    app.run_polling()


if __name__ == "__main__":
    main()
