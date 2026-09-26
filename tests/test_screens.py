"""Screen model: browsing costs zero messages, and the edges that used to bite.

Every test here drives the real handlers through Driver, which taps buttons on
the message at the bottom of the chat - the way a person actually does it.
"""
import asyncio
import pytest
from modules.config import load_config
from modules.database import Database
from doubles import Driver, FakeBot, make_ctx, make_update, screen_labels


@pytest.fixture()
def env(tmp_path):
    from modules.course_engine import seed_from_json
    db = Database(str(tmp_path / "s.db"))
    db.migrate()
    seed_from_json(db, "c", {"title": "T", "episodes": [
        {"no": 1, "title": "Ep One", "parts": [{"no": 1, "kind": "text", "text": "body one"}]},
        {"no": 2, "title": "Ep Two", "parts": [{"no": 1, "kind": "text", "text": "body two"}]}]})
    db.execute("UPDATE episodes SET caption='body one' WHERE episode_no=1")
    db.execute("UPDATE episodes SET caption='body two' WHERE episode_no=2")
    cfg = load_config({"ADMIN_IDS": "1", "COURSE_SLUG": "c"})
    yield db, cfg
    db.close()


def registered(db, uid):
    from modules.users import get_or_create, set_name, set_phone
    u = get_or_create(db, uid, None)
    set_phone(db, u["id"], "09120000000")
    set_name(db, u["id"], "تست")
    c = db.fetchone("SELECT id FROM courses WHERE slug='c'")
    db.execute("UPDATE users SET current_course_id=? WHERE id=?", (c["id"], u["id"]))
    return u


# ------------------------------------------------------------ the headline


def test_browsing_menus_adds_zero_messages(env):
    """The whole point: wandering the menus must not grow the chat."""
    from bot.handlers import cmd_start
    db, cfg = env
    registered(db, 40)
    d = Driver(db, cfg, 40)
    d.run(cmd_start)
    assert d.message_count == 1
    for _ in range(6):
        d.tap("menu:catalog")
        d.tap("menu:main")
    assert d.message_count == 1, "menu browsing must reuse one message"
    assert d.live_count == 1
    assert not d.bot.deleted, "an in-place edit deletes nothing"


def alerts_silent(*queries):
    """True when no query ever showed the user a toast or an alert."""
    for q in queries:
        for args, kwargs in q.answered:
            if args or kwargs.get("show_alert"):
                return False
    return True


def test_double_tapping_a_menu_button_is_not_an_error(env):
    """Telegram answers 'Message is not modified' on a repaint. The user must see
    nothing at all: no alert, no duplicate message, and the screen left as it is."""
    from bot.handlers import cmd_start
    db, cfg = env
    registered(db, 41)
    d = Driver(db, cfg, 41)
    d.run(cmd_start)
    taps = [d.run(_cb, data="menu:main") for _ in range(3)]
    assert all(q.callback_query.answered for q in taps), "the spinner must be dismissed"
    assert alerts_silent(*[q.callback_query for q in taps]), "a no-op repaint must be silent"
    assert len(taps[0].callback_query.edited) == 1, "the first tap paints the menu"
    assert not taps[1].callback_query.edited, "an identical repaint is swallowed, not retried"
    assert not taps[2].callback_query.edited
    assert d.message_count == 1
    assert d.live_count == 1


def test_episode_content_is_never_edited_or_deleted(env):
    """Content is the user's to keep: menus come and go, the episode stays."""
    from bot.handlers import cmd_start
    db, cfg = env
    registered(db, 42)
    d = Driver(db, cfg, 42)
    d.run(cmd_start)
    catalog_id = d.bot.bottom
    d.tap("ep:1")
    assert d.message_count == 2                      # catalog + episode
    episode_id = d.bot.bottom
    for _ in range(4):
        d.tap("menu:main")
        d.tap("ep:1")
    assert episode_id in d.bot.live, "the episode the user read must survive"
    assert episode_id not in d.bot.deleted
    assert "body one" in d.bot.live[episode_id].text
    assert catalog_id not in d.bot.live, "the old screen was cleared away"


def test_menu_from_episode_lands_where_the_user_looks(env):
    """Editing a screen that is 20 messages up would change nothing on screen, so
    the screen is moved down to the tapper instead."""
    from bot.handlers import cmd_start
    db, cfg = env
    registered(db, 43)
    d = Driver(db, cfg, 43)
    d.run(cmd_start)
    catalog_id = d.bot.bottom
    d.tap("ep:1")
    d.tap("menu:main")
    assert d.bot.deleted == [catalog_id], "the stale screen is cleared away"
    assert d.message_count == 3, "one screen, moved down: catalog out, menu in, episode kept"
    assert d.live_count == 2
    assert d.bot.bottom not in (catalog_id,)


def test_stale_screen_that_cannot_be_deleted_is_survivable(env):
    """Telegram refuses deletes past 48h. Losing the race must not break the flow."""
    from bot.handlers import cmd_start
    db, cfg = env
    registered(db, 44)
    d = Driver(db, cfg, 44, delete_fails=True)
    d.run(cmd_start)
    d.tap("ep:1")
    d.tap("menu:main")
    d.tap("menu:main")
    assert d.bot.deleted == [], "deletion was refused"
    assert "اپیزود" in d.tap("menu:main") or d.bottom is not None


def test_restart_forgets_the_screen_but_stays_correct(env):
    """ctx.user_data is in memory. A restart must cost a leftover message, not a
    wrong deletion."""
    from bot.handlers import cmd_start
    db, cfg = env
    registered(db, 45)
    d = Driver(db, cfg, 45)
    d.run(cmd_start)
    fresh = Driver(db, cfg, 45)
    fresh.bot = d.bot                       # same chat, brand new memory
    fresh.ctx = make_ctx(db, cfg, d.bot)
    fresh.run(cmd_start)
    assert d.bot.deleted == [], "nothing to delete: the bot never saw it"
    assert d.bot.bottom is not None


# ------------------------------------------------------------ dead buttons


def test_deleted_episode_button_warns_and_takes_its_keys_off(env):
    """An old menu keeps its buttons after the episode is gone. Tapping one used
    to do nothing at all, leaving the spinner running."""
    from bot.handlers import cmd_start
    db, cfg = env
    registered(db, 46)
    d = Driver(db, cfg, 46)
    d.run(cmd_start)
    stale_id = d.bot.bottom
    db.execute("DELETE FROM episodes WHERE episode_no=1")
    u = d.run(_cb, data="ep:1")
    alerts = [a[0][0] for a in u.callback_query.answered if a and a[0]]
    assert alerts and "در دسترس" in alerts[0]
    labels = screen_labels(d.bot.live[stale_id].reply_markup)
    assert labels == ["🏠 منو"], "only an escape hatch is left"
    assert d.message_count == 1, "a dead button must not spawn a message"


def test_callback_over_64_bytes_is_rejected():
    """Telegram drops the whole button at creation time past 64 bytes."""
    from modules.telegram_core import CALLBACK_MAX_BYTES, validate_callback
    assert validate_callback("adm:ep:" + "a" * 40)
    assert not validate_callback("adm:ep:" + "a" * 80)
    assert CALLBACK_MAX_BYTES == 64


# ------------------------------------------------------------ other chats


def test_group_chat_never_edits_or_deletes():
    """One shared surface would fight every member. In a group, views only add."""
    from bot.handlers import show_catalog
    db = Database(":memory:")
    db.migrate()
    cfg = load_config({"ADMIN_IDS": "1", "COURSE_SLUG": "c"})
    bot = FakeBot(chat_id=-100)
    ctx = make_ctx(db, cfg, bot)
    u = make_update(47, query_data="menu:catalog", bot=bot, chat_id=-100)
    u.effective_chat.type = "supergroup"
    asyncio.run(show_catalog(u, ctx, {"id": 1}))
    u2 = make_update(47, query_data="menu:catalog", bot=bot, chat_id=-100)
    u2.effective_chat.type = "supergroup"
    asyncio.run(show_catalog(u2, ctx, {"id": 1}))
    assert not u.callback_query.edited and not u2.callback_query.edited
    assert not bot.deleted
    assert len(bot.screens) == 2
    db.close()


# ------------------------------------------------------------ the offer link


def test_purchase_link_is_scheduled_to_disappear(env):
    """A checkout URL is not worth a permanent line in the chat."""
    from bot.handlers import cmd_start
    from modules.offers import upsert_offer
    db, cfg = env
    registered(db, 48)
    upsert_offer(db, "o", "OTitle", "Body", "https://x.test/buy", "buy", "always")
    jobs = FakeJobQueue()
    d = Driver(db, cfg, 48, job_queue=jobs)
    jobs.bot = d.bot
    d.run(cmd_start)
    d.tap("offer:menu")
    u = d.run(_cb, data="offer:o")
    assert any("https://x.test/buy" in t for t, _ in u.effective_message.sent)
    assert len(jobs.scheduled) == 1
    seconds, callback, mid, chat_id = jobs.scheduled[0]
    assert seconds == 30 and chat_id == 48 and mid is not None
    # the link is a plain message, not a screen: it must not become the surface
    assert "https://x.test/buy" not in " ".join(t for t, _ in d.bot.screens)
    # and the expiry must actually reach the bot, not die on a wrong attribute
    assert jobs.fire() == 1
    assert mid in d.bot.deleted


def test_no_job_queue_leaves_the_link_in_place(env):
    from bot.handlers import cmd_start
    from modules.offers import upsert_offer
    db, cfg = env
    registered(db, 49)
    upsert_offer(db, "o", "OTitle", "Body", "https://x.test/buy", "buy", "always")
    d = Driver(db, cfg, 49)
    d.run(cmd_start)
    d.tap("offer:menu")
    u = d.run(_cb, data="offer:o")
    assert any("https://x.test/buy" in t for t, _ in u.effective_message.sent)


# ------------------------------------------------------------ admin panel


def test_admin_double_tap_is_not_an_error(env):
    """Same trap, same fix: the panel must not scold the admin for tapping twice.
    The second tap is a no-op edit, not a new message and not an error alert."""
    from bot.admin_handlers import cmd_admin, on_admin_callback
    db, cfg = env
    bot = FakeBot(chat_id=1)
    ctx = make_ctx(db, cfg, bot)
    panel = 500
    asyncio.run(cmd_admin(make_update(1), ctx))
    seen = []
    for _ in range(3):
        u = make_update(1, query_data="adm:menu", bot=bot, message_id=panel)
        asyncio.run(on_admin_callback(u, ctx))
        seen.append(u)
    assert not any("خطا" in a for a, _ in seen[-1].callback_query.answered)
    assert len(seen[0].callback_query.edited) == 1, "first tap paints the panel"
    assert not seen[1].callback_query.edited, "identical repaint is swallowed"
    assert not seen[2].callback_query.edited
    assert alerts_silent(*[u.callback_query for u in seen])


def live_with(d, needle):
    """Live (not deleted) messages whose text contains needle."""
    return [m for m in d.bot.live.values() if needle in (m.text or "")]


def offer_views(db):
    return db.fetchone("SELECT COUNT(*) c FROM offer_interactions WHERE kind='viewed'")["c"]


def test_re_watching_the_last_episode_leaves_your_menu_alone(env):
    """The guard is not about the count in the chat - the screen mechanism already
    caps that at one. It is about the side effects: without it, every re-watch
    re-fired the celebration, so the user got a 'تبریک' thrown at them each time
    instead of the episode they asked for."""
    from bot.handlers import cmd_start
    db, cfg = env
    registered(db, 54)
    d = Driver(db, cfg, 54)
    d.run(cmd_start)
    d.tap("ep:1")
    d.tap("ep:2")
    assert len(live_with(d, "تبریک")) == 1, "finishing celebrates exactly once"
    for _ in range(3):
        d.tap("menu:main")
        menus = live_with(d, "Ep One")
        assert len(menus) == 1, "never two menus at once"
        assert "تبریک" not in menus[0].text, "the menu is not a celebration"
        d.tap("ep:2")
        assert not live_with(d, "تبریک"), "re-watching must not start celebrating again"
    # the model, stated as a number: one message per episode opened, plus exactly
    # one menu. Content is the user's to keep; the menu never multiplies.
    assert d.live_count == 2 + 3 + 1


def test_re_watching_does_not_inflate_the_offer_stats(env):
    """Re-firing the celebration re-logged the offer as 'viewed', so the CTR the
    admin reads in /admin was counting the same impression again and again."""
    from bot.handlers import cmd_start
    from modules.offers import upsert_offer
    db, cfg = env
    registered(db, 55)
    upsert_offer(db, "o", "OTitle", "OfferBody", "https://x.test/buy", "buy", "always")
    d = Driver(db, cfg, 55)
    d.run(cmd_start)
    d.tap("ep:1")
    d.tap("ep:2")
    first = offer_views(db)
    assert first == 1
    for _ in range(3):
        d.tap("ep:2")
    assert offer_views(db) == first, "one impression per completion, not per re-watch"


def test_finishing_the_course_does_not_stack_congratulations(env):
    """The bug in the screenshot: re-opening the last episode used to append a
    fresh 'تبریک' every time, because the celebration was a pushed message with
    no memory of whether it had already happened."""
    from bot.handlers import cmd_start
    db, cfg = env
    registered(db, 51)
    d = Driver(db, cfg, 51)
    d.run(cmd_start)
    d.tap("ep:1")
    d.tap("ep:2")
    assert len(live_with(d, "تبریک")) == 1, "finishing celebrates exactly once"
    peak = 1
    for _ in range(4):
        d.tap("menu:main")
        d.tap("menu:catalog")
        d.tap("course:c")
        d.tap("ep:2")
        peak = max(peak, len(live_with(d, "تبریک")))
    assert peak == 1, "wandering in and out never adds a second celebration"
    assert len(live_with(d, "تبریک")) <= 1


def test_the_menu_stays_the_menu_after_the_course_is_done(env):
    """It used to swap its own title for the congratulations, so every tap on
    '🏠 منو' read like another celebration and hid which course it was."""
    from bot.handlers import cmd_start
    db, cfg = env
    registered(db, 53)
    d = Driver(db, cfg, 53)
    d.run(cmd_start)
    d.tap("ep:1")
    d.tap("ep:2")
    d.tap("menu:main")
    bottom = d.bottom
    assert "تبریک" not in bottom.text, "the menu is not a celebration"
    assert "T" in bottom.text, "the menu still names its course"
    labels = screen_labels(bottom.reply_markup)
    assert any("Ep One" in t for t in labels) and any("Ep Two" in t for t in labels)


def test_celebration_carries_the_offer_on_one_screen(env):
    """Celebration and offer used to be two pushes competing for the same spot."""
    from bot.handlers import cmd_start
    from modules.offers import upsert_offer
    db, cfg = env
    registered(db, 52)
    upsert_offer(db, "o", "OTitle", "OfferBody", "https://x.test/buy", "buy", "always")
    d = Driver(db, cfg, 52)
    d.run(cmd_start)
    d.tap("ep:1")
    d.tap("ep:2")
    assert len(live_with(d, "تبریک")) == 1
    assert len(live_with(d, "OTitle")) == 1
    both = [m for m in d.bot.live.values()
            if "تبریک" in (m.text or "") and "OTitle" in (m.text or "")]
    assert both, "both belong to the same screen"
    labels = screen_labels(d.bottom.reply_markup)
    assert "buy" in labels and "🏠 منو" in labels


class FakeJobQueue:
    """Mirrors PTB: run_once stores (callback, seconds, data, chat_id) and the
    callback is invoked with a CallbackContext whose bot is on the context and
    whose ids live on context.job. Executing it here is the point - a fake that
    only records the call would happily pass a broken callback."""

    def __init__(self, bot=None):
        self.bot = bot
        self.scheduled = []

    def run_once(self, callback, seconds, data=None, chat_id=None, **kw):
        self.scheduled.append((seconds, callback, data, chat_id))
        return object()

    def fire(self):
        """Run every scheduled callback, as the queue would."""
        from types import SimpleNamespace
        for _seconds, callback, data, chat_id in self.scheduled:
            job = SimpleNamespace(chat_id=chat_id, user_id=None, data=data, name=None)
            asyncio.run(callback(SimpleNamespace(bot=self.bot, job=job)))
        return len(self.scheduled)


async def _cb(update, ctx):
    from bot.handlers import on_callback
    await on_callback(update, ctx)
