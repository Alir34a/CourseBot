"""Bot UX: onboarding guidance, help, review navigation, media delivery, outbox."""
import asyncio
import pytest
from modules.config import load_config
from modules.database import Database
from doubles import FakeBot, make_ctx, make_update, screen_labels, view_of


@pytest.fixture()
def env(tmp_path):
    from modules.course_engine import seed_from_json
    db = Database(str(tmp_path / "u.db"))
    db.migrate()
    seed_from_json(db, "c", {"title": "T", "episodes": [
        {"no": 1, "title": "Ep One", "parts": [
            {"no": 1, "kind": "text", "text": "hello"},
            {"no": 2, "kind": "video", "text": "watch", "file_id": "VID123"}]},
        {"no": 2, "title": "Ep Two", "parts": [{"no": 1, "kind": "text", "text": "t2"}]}]})
    cfg = load_config({"ADMIN_IDS": "1", "COURSE_SLUG": "c"})
    bot = FakeBot()
    yield db, cfg, bot
    db.close()


def ctx_of(db, cfg, bot, user_data=None):
    return make_ctx(db, cfg, bot, user_data)


def upd(uid, text="", query=None, bot=None, message_id=None):
    return make_update(uid, text, query, bot, message_id)


def registered(db, uid=10):
    from modules.users import get_or_create, set_phone, set_name
    u = get_or_create(db, uid, None)
    from modules.users import set_phone as sp
    sp(db, u["id"], "09120000000")
    u = set_name(db, u["id"], "تست")
    c = db.fetchone("SELECT id FROM courses WHERE slug='c'")
    db.execute("UPDATE users SET current_course_id=? WHERE id=?", (c["id"], u["id"]))
    return u


def test_typed_phone_gets_guidance(env):
    from bot.handlers import on_text
    db, cfg, bot = env
    u = upd(20, "09123456789")
    asyncio.run(on_text(u, ctx_of(db, cfg, bot)))
    assert any("دکمه" in t for t, _ in u.effective_message.sent)
    assert db.fetchone("SELECT id FROM users WHERE telegram_id=20") is None  # no row from typing


def test_random_text_gets_phone_prompt(env):
    from bot.handlers import on_text
    db, cfg, bot = env
    u = upd(21, "سلام")
    asyncio.run(on_text(u, ctx_of(db, cfg, bot)))
    assert any("شماره موبایل" in t for t, _ in u.effective_message.sent)


def test_name_digits_rejected(env):
    from bot.handlers import on_text
    from modules.users import get_or_create, set_phone
    db, cfg, bot = env
    u0 = get_or_create(db, 22, None)
    set_phone(db, u0["id"], "09120000001")
    u = upd(22, "09123456789")
    asyncio.run(on_text(u, ctx_of(db, cfg, bot, {"awaiting": "name"})))
    assert any("شماره موبایل" in t or "اسم" in t for t, _ in u.effective_message.sent)
    assert db.fetchone("SELECT full_name FROM users WHERE telegram_id=22")["full_name"] is None


def test_registered_text_shows_menu(env):
    from bot.handlers import on_text
    db, cfg, bot = env
    registered(db, 23)
    u = upd(23, "چیزی")
    asyncio.run(on_text(u, ctx_of(db, cfg, bot)))
    texts = [t for t, _ in u.effective_message.sent]
    assert any("دکمه" in t for t in texts)              # the nudge answers the message
    assert bot.screens and "دوره‌ها" in bot.screens[-1][0]  # the catalog is a screen


def test_help_and_episodes_commands(env):
    from bot.handlers import cmd_episodes, cmd_help
    db, cfg, bot = env
    u = upd(24, "")
    asyncio.run(cmd_help(u, ctx_of(db, cfg, bot)))
    assert any("/start" in t for t, _ in u.effective_message.sent)
    u2 = upd(24, "")
    asyncio.run(cmd_episodes(u2, ctx_of(db, cfg, bot)))
    assert any("/start" in t for t, _ in u2.effective_message.sent)
    registered(db, 25)
    u3 = upd(25, "")
    asyncio.run(cmd_help(u3, ctx_of(db, cfg, bot)))
    assert any("/episodes" in t for t, _ in u3.effective_message.sent)


def test_menu_offer_button_eligibility(env):
    from bot.handlers import show_menu
    from modules.offers import upsert_offer
    db, cfg, bot = env
    u = registered(db, 26)
    upsert_offer(db, "o", "T", "X", "https://x.test", "buy", "always")
    w = upd(26, query="menu:main")
    asyncio.run(show_menu(w, ctx_of(db, cfg, bot), db.fetchone("SELECT * FROM users WHERE telegram_id=26")))
    assert any("پیشنهاد" in t for t in screen_labels(view_of(w, bot)[1]))
    upsert_offer(db, "o", "T", "X", "https://x.test", "buy", "episode:99")
    w2 = upd(26, query="menu:main")
    asyncio.run(show_menu(w2, ctx_of(db, cfg, bot), db.fetchone("SELECT * FROM users WHERE telegram_id=26")))
    assert not any("پیشنهاد" in t for t in screen_labels(view_of(w2, bot)[1]))


def test_episode_text_delivery_has_nav(env):
    from bot.handlers import show_episode
    from modules.course_engine import get_course
    db, cfg, bot = env
    registered(db, 27)
    c = get_course(db, "c")
    db.execute("UPDATE episodes SET caption='hello body' WHERE episode_no=1")
    w = upd(27, query="ep:1")
    asyncio.run(show_episode(w, ctx_of(db, cfg, bot),
                             db.fetchone("SELECT * FROM users WHERE telegram_id=27"), c, 1))
    texts = [t for _, t in bot.calls]
    assert any("hello body" in t for t in texts)
    assert "اپیزود" in texts[-1]  # progress + nav ride on the last message


def test_episode_media_delivery_and_autocomplete(env):
    from bot.handlers import show_episode
    from modules.course_engine import get_course, set_episode_media
    from modules.progress import progress_summary
    db, cfg, bot = env
    u = registered(db, 28)
    c = get_course(db, "c")
    ep = db.fetchone("SELECT id FROM episodes WHERE episode_no=1")
    set_episode_media(db, ep["id"], "video", "VID123")
    w = upd(28, "")
    asyncio.run(show_episode(w, ctx_of(db, cfg, bot),
                             db.fetchone("SELECT * FROM users WHERE telegram_id=28"), c, 1))
    kinds = [k for k, _ in bot.calls]
    assert "video" in kinds and bot.calls[0][1] == "VID123"
    assert progress_summary(db, u["id"], "c")["done"] >= 1  # open = seen


def test_legacy_part_callbacks_degrade_to_episode(env):
    from bot.handlers import on_callback
    db, cfg, bot = env
    registered(db, 29)
    for data in ("part:1:1", "parts:1", "done:1:1"):
        w = upd(29, query=data)
        asyncio.run(on_callback(w, ctx_of(db, cfg, bot)))  # must not crash
    assert bot.calls, "episode content must be delivered"


def test_offer_menu_callback(env):
    from bot.handlers import on_callback
    from modules.offers import upsert_offer
    db, cfg, bot = env
    registered(db, 30)
    upsert_offer(db, "o2", "OTitle", "X", "https://x.test", "buy", "always")
    w = upd(30, query="offer:menu", bot=bot)
    asyncio.run(on_callback(w, ctx_of(db, cfg, bot)))
    shown = view_of(w, bot)
    assert shown and "OTitle" in shown[0]
    # an offer card the user cannot leave is a dead end
    assert any("منو" in t for t in screen_labels(shown[1]))


def test_outbox_actually_delivers(env):
    from modules.messaging import queue_message, send_queued
    from modules.users import get_or_create, set_phone
    db, cfg, bot = env
    u0 = get_or_create(db, 31, None)
    set_phone(db, u0["id"], "09120000002")
    queue_message(db, "سلام گروهی", scope="filtered", filter_json={})
    res = asyncio.run(send_queued(db, bot))
    assert res["sent"] == 1 and res["failed"] == 0
    assert any("سلام گروهی" in t for _, t in bot.calls)
    assert db.fetchone("SELECT status FROM outbox_messages")["status"] == "sent"
