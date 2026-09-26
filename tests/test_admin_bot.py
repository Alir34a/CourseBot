"""Admin-in-Telegram: gating (silence for strangers), validators, wizard routing."""
import asyncio
import pytest
from modules.config import load_config
from modules.database import Database
from doubles import make_ctx as _ctx, make_update as _update


def make_ctx(db, admin_ids=(1,)):
    cfg = load_config({"ADMIN_IDS": ",".join(map(str, admin_ids)), "COURSE_SLUG": "c"})
    return _ctx(db, cfg)


def make_update(uid, text="", query_data=None):
    return _update(uid, text, query_data)


@pytest.fixture()
def db(tmp_path):
    from modules.course_engine import seed_from_json
    d = Database(str(tmp_path / "a.db"))
    d.migrate()
    seed_from_json(d, "c", {"title": "T", "episodes": [
        {"no": 1, "title": "E1", "parts": [{"no": 1, "kind": "text", "text": "x"}]}]})
    yield d
    d.close()


def test_nonadmin_gets_silence(db):
    from bot.admin_handlers import cmd_admin, on_admin_callback
    ctx = make_ctx(db)
    u = make_update(999, query_data="adm:stats")
    asyncio.run(cmd_admin(make_update(999), ctx))
    asyncio.run(on_admin_callback(u, ctx))
    assert u.callback_query.answered  # spinner dismissed, nothing else
    assert not u.callback_query.edited


def test_admin_gets_menu(db):
    from bot.admin_handlers import cmd_admin
    ctx = make_ctx(db)
    u = make_update(1)
    asyncio.run(cmd_admin(u, ctx))
    assert any("پنل مدیریت" in t for t, _ in u.effective_message.sent)


def test_forged_admin_callback_rejected(db):
    from bot.admin_handlers import on_admin_callback
    ctx = make_ctx(db)
    u = make_update(1, query_data="adm:; DROP TABLE users--")
    asyncio.run(on_admin_callback(u, ctx))
    assert u.callback_query.answered
    assert not u.callback_query.edited


def test_validators():
    from bot.admin_handlers import v_ep_no, v_slug, v_trigger, v_url
    assert v_ep_no("16") == 16
    assert v_slug("vip-course") == "vip-course"
    assert v_url("https://x.test/buy").startswith("https")
    assert v_trigger("episode:15") == "episode:15" and v_trigger("always") == "always"
    for fn, bad in [(v_ep_no, "abc"), (v_ep_no, "0"), (v_slug, "bad slug!"),
                    (v_url, "notaurl"), (v_trigger, "ep:99")]:
        with pytest.raises(ValueError):
            fn(bad)


def test_wizard_routing(db):
    from bot.admin_handlers import admin_consume_media, admin_consume_text
    ctx = make_ctx(db)
    assert asyncio.run(admin_consume_text(make_update(999, "16"), ctx)) is False  # stranger
    assert asyncio.run(admin_consume_text(make_update(1, "hi"), ctx)) is False    # no flow
    assert asyncio.run(admin_consume_media(make_update(1), ctx)) is False         # no flow
    ctx.user_data["adm"] = {"flow": "epadd", "step": "title", "data": {}}
    assert asyncio.run(admin_consume_text(make_update(1, "عنوان"), ctx)) is True
    assert ctx.user_data["adm"]["step"] == "content"


def test_full_epadd_wizard_saves(db):
    from bot.admin_handlers import admin_consume_text
    from modules.course_engine import get_episode
    ctx = make_ctx(db)
    ctx.user_data["adm"] = {"flow": "epadd", "step": "title", "data": {}}
    asyncio.run(admin_consume_text(make_update(1, "عنوان تستی"), ctx))
    asyncio.run(admin_consume_text(make_update(1, "-"), ctx))
    assert "adm" not in ctx.user_data
    assert get_episode(db, "c", 2)["title"] == "عنوان تستی"  # auto-numbered after existing ep 1


def test_stats_renders(db):
    from bot.admin_handlers import stats_text
    txt = stats_text(db, "c")
    assert "Ep1" in txt and "تکمیل" in txt
