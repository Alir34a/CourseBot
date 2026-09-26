"""Admin-as-user: rewording copy from the screen he is looking at.

The point of the feature is a loop - preview, reword, see it live - so most of
these tests drive the whole loop rather than asserting on a single button.
"""
import asyncio
import pytest
from modules.config import load_config
from modules.database import Database
from doubles import FakeBot, make_ctx, make_update, screen_labels

PAGE_BTN = "✏️ متن‌های این صفحه"


@pytest.fixture()
def env(tmp_path):
    from modules.course_engine import seed_from_json
    from modules.users import get_or_create, set_name, set_phone
    db = Database(str(tmp_path / "copy.db"))
    db.migrate()
    seed_from_json(db, "c", {"title": "T", "episodes": [
        {"no": 1, "title": "E1", "parts": [{"no": 1, "kind": "text", "text": "x"}]},
        {"no": 2, "title": "E2", "parts": [{"no": 1, "kind": "text", "text": "x"}]}]})
    db.execute("UPDATE episodes SET caption='body' WHERE episode_no=1")
    cfg = load_config({"ADMIN_IDS": "1", "COURSE_SLUG": "c"})
    admin = get_or_create(db, 1, None)
    set_phone(db, admin["id"], "09120000000")
    set_name(db, admin["id"], "Admin")
    guest = get_or_create(db, 500, None)
    set_phone(db, guest["id"], "09120000001")
    set_name(db, guest["id"], "مهمان")
    cid = db.fetchone("SELECT id FROM courses WHERE slug='c'")["id"]
    db.execute("UPDATE users SET current_course_id=? WHERE id IN (?,?)", (cid, admin["id"], guest["id"]))
    yield db, cfg
    db.close()


def session(db, cfg, uid):
    bot = FakeBot(chat_id=uid)
    ctx = make_ctx(db, cfg, bot)
    return bot, ctx


def tap(bot, ctx, uid, data):
    u = make_update(uid, "", data, bot, message_id=bot.bottom)
    from bot.handlers import on_callback
    asyncio.run(on_callback(u, ctx))
    return u


def adm(bot, ctx, uid, data):
    u = make_update(uid, "", data, bot, message_id=bot.bottom)
    from bot.admin_handlers import on_admin_callback
    asyncio.run(on_admin_callback(u, ctx))
    return u


def say(db, ctx, bot, uid, text):
    from bot.admin_handlers import admin_consume_text
    u = make_update(uid, text, None, bot, message_id=bot.bottom)
    asyncio.run(admin_consume_text(u, ctx))
    return u


def press(bot, ctx, uid, label):
    """Tap a button by its visible label, the way a person does. Going through the
    label is the point: a test that hand-writes the callback_data would happily
    pass while the real button is wired to the wrong target."""
    rows = bot.live[bot.bottom].reply_markup.inline_keyboard
    for row in rows:
        for b in row:
            if label in b.text:
                return tap(bot, ctx, uid, b.callback_data) if not b.callback_data.startswith("adm:") \
                    else adm(bot, ctx, uid, b.callback_data)
    raise AssertionError(f"no button labelled {label!r} on: "
                         f"{[b.text for r in rows for b in r]}")


def labels(bot):
    kb = bot.live[bot.bottom].reply_markup
    return screen_labels(kb) if kb else []


# ------------------------------------------------------------- the loop


def test_admin_rewords_a_button_and_sees_it_live(env):
    """The whole feature in one test: the admin stands on the menu, rewords the
    'courses' button, walks back through the buttons he is actually shown, and the
    new wording is there."""
    from bot.handlers import cmd_start
    db, cfg = env
    bot, ctx = session(db, cfg, 1)
    asyncio.run(cmd_start(make_update(1, "", None, bot), ctx))
    tap(bot, ctx, 1, "course:c")
    assert PAGE_BTN in labels(bot)

    press(bot, ctx, 1, PAGE_BTN)
    press(bot, ctx, 1, "دکمهٔ دوره‌ها")
    assert "مقدار فعلی" in bot.live[bot.bottom].text
    say(db, ctx, bot, 1, "📚 فهرست دوره‌ها")
    assert "🔙 بازگشت به صفحه" in labels(bot), "the way home must be offered"

    press(bot, ctx, 1, "🔙 بازگشت به صفحه")
    now = labels(bot)
    assert "📚 فهرست دوره‌ها" in now, "the rewording is live on the menu"
    assert "📚 دوره‌ها" not in now
    assert PAGE_BTN in now, "and the admin is still an admin here"


def test_ordinary_users_never_see_the_edit_button(env):
    """Hidden for convenience only - and it must be hidden, since a button that
    answers 'access denied' is worse than no button."""
    from bot.handlers import cmd_start
    db, cfg = env
    bot, ctx = session(db, cfg, 500)
    asyncio.run(cmd_start(make_update(500, "", None, bot), ctx))
    tap(bot, ctx, 500, "course:c")
    assert PAGE_BTN not in labels(bot)


def test_a_guest_cannot_reach_the_editor_even_by_forging_the_button(env):
    """Hiding a button is not security. on_admin_callback must refuse on its own."""
    db, cfg = env
    bot, ctx = session(db, cfg, 500)
    adm(bot, ctx, 500, "adm:textsof:menu:menu:main")
    assert not bot.screens, "a stranger must not paint an admin screen"
    adm(bot, ctx, 500, "adm:text:btn_courses:menu:main")
    assert db.fetchone("SELECT value FROM settings WHERE key='text:btn_courses'") is None


def test_the_chooser_lists_exactly_that_screen_texts(env):
    """Four extra buttons on the menu is how a menu stops looking like a menu, so
    there is one button per screen and the chooser carries the list."""
    from bot.handlers import PAGE_EDIT_KEYS, cmd_start
    db, cfg = env
    bot, ctx = session(db, cfg, 1)
    asyncio.run(cmd_start(make_update(1, "", None, bot), ctx))
    adm(bot, ctx, 1, "adm:textsof:catalog:menu:catalog")
    shown = labels(bot)
    for key in PAGE_EDIT_KEYS["catalog"]:
        assert any(key in b.callback_data for b in
                   [b for row in bot.live[bot.bottom].reply_markup.inline_keyboard for b in row])
    assert "🔙 بازگشت به صفحه" in shown
    # and the payload fits Telegram's 64-byte button budget
    for row in bot.live[bot.bottom].reply_markup.inline_keyboard:
        for b in row:
            assert len(b.callback_data.encode()) <= 64, b.callback_data


# ------------------------------------------------------------- undo


def test_a_reworded_text_can_go_back_to_default(env):
    """A white-label edit with no undo is a one-way door."""
    from bot.texts import DEFAULTS, is_overridden, t
    db, cfg = env
    bot, ctx = session(db, cfg, 1)
    adm(bot, ctx, 1, "adm:text:btn_courses:")
    say(db, ctx, bot, 1, "📚 فهرست دوره‌ها")
    assert is_overridden(db, "btn_courses")
    assert t(db, "btn_courses") == "📚 فهرست دوره‌ها"
    adm(bot, ctx, 1, "adm:textreset:btn_courses")
    assert not is_overridden(db, "btn_courses")
    assert t(db, "btn_courses") == DEFAULTS["btn_courses"]


def test_resetting_an_untouched_text_says_so_instead_of_lying(env):
    db, cfg = env
    bot, ctx = session(db, cfg, 1)
    u = adm(bot, ctx, 1, "adm:textreset:btn_courses")
    alerts = [a[0][0] for a in u.callback_query.answered if a and a[0]]
    assert alerts and "پیش‌فرض" in alerts[0]


def test_overridden_texts_are_marked_in_both_lists(env):
    """Otherwise the admin cannot tell his own copy from the shipped one."""
    from bot.texts import is_overridden
    db, cfg = env
    bot, ctx = session(db, cfg, 1)
    adm(bot, ctx, 1, "adm:text:btn_courses:")
    say(db, ctx, bot, 1, "📚 فهرست دوره‌ها")
    adm(bot, ctx, 1, "adm:texts")
    assert any("✱" in t for t in labels(bot))
    adm(bot, ctx, 1, "adm:textsof:menu:menu:main")
    assert any("✱" in t for t in labels(bot))
    assert is_overridden(db, "btn_courses")


# ------------------------------------------------------------- safety


def test_a_second_edit_while_mid_wizard_is_refused(env):
    """ctx.user_data['adm'] holds exactly one flow. Tapping an edit button while
    building an episode would silently destroy the episode."""
    db, cfg = env
    bot, ctx = session(db, cfg, 1)
    ctx.user_data["adm"] = {"flow": "epadd", "step": "title", "data": {}}
    u = adm(bot, ctx, 1, "adm:text:btn_courses:menu:main")
    alerts = [a[0][0] for a in u.callback_query.answered if a and a[0]]
    assert alerts and "ناتمام" in alerts[0]
    assert ctx.user_data["adm"]["flow"] == "epadd", "the running wizard survives"
    assert not bot.screens, "and no editor was opened"


def test_a_text_with_a_placeholder_dropped_does_not_crash(env):
    """An admin reworded the progress line to 'پیشرفت شما' and left {total} out."""
    from bot.handlers import cmd_start
    db, cfg = env
    bot, ctx = session(db, cfg, 1)
    adm(bot, ctx, 1, "adm:text:catalog_progress:")
    say(db, ctx, bot, 1, "پیشرفت شما")
    asyncio.run(cmd_start(make_update(1, "", None, bot), ctx))
    tap(bot, ctx, 1, "course:c")
    assert "پیشرفت شما" in bot.live[bot.bottom].text
    tap(bot, ctx, 1, "ep:1")
    assert any("پیشرفت شما" in t for _, t in bot.calls)


def test_editing_a_label_the_admin_cannot_see_is_impossible(env):
    """The chooser is built from PAGE_EDIT_KEYS, so a forged key cannot open an
    editor for a text this bot does not use."""
    db, cfg = env
    bot, ctx = session(db, cfg, 1)
    adm(bot, ctx, 1, "adm:text:no_such_key:menu:main")
    assert not bot.screens
    adm(bot, ctx, 1, "adm:textsof:no_such_page:menu:main")
    assert not bot.screens
