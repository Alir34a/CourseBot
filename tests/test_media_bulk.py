"""Media intake (all 6 kinds), bulk import, after-save nav, course-delete detach."""
import asyncio
from types import SimpleNamespace
import pytest
from modules.config import load_config
from modules.database import Database
from doubles import FakeBot, FakeMsg, make_ctx, make_update


@pytest.fixture()
def env(tmp_path):
    from modules.course_engine import seed_from_json
    db = Database(str(tmp_path / "m.db"))
    db.migrate()
    seed_from_json(db, "c", {"title": "T", "episodes": [
        {"no": 1, "title": "E1", "parts": [{"no": 1, "kind": "text", "text": "x"}]}]})
    cfg = load_config({"ADMIN_IDS": "1", "COURSE_SLUG": "c"})
    yield db, cfg, FakeBot()
    db.close()


def actx(db, cfg, bot, user_data=None):
    return make_ctx(db, cfg, bot, user_data)


def aupd(uid, msg=None, query=None, bot=None, message_id=None):
    u = make_update(uid, msg.text if msg else "", query, bot, message_id)
    if msg is not None:
        u.effective_message = msg
    return u


@pytest.mark.parametrize("attr,fid,want", [
    ("photo", "P1", "photo"), ("video", "V1", "video"), ("audio", "A1", "audio"),
    ("voice", "VC1", "voice"), ("video_note", "VN1", "video_note"), ("document", "D1", "file"),
])
def test_media_intake_all_kinds(env, attr, fid, want):
    from bot.admin_handlers import admin_consume_media
    db, cfg, bot = env
    ep = db.fetchone("SELECT id FROM episodes WHERE episode_no=1")
    ctx = actx(db, cfg, bot, {"adm": {"flow": "mediaadd", "step": "media",
                                      "data": {"ep_id": ep["id"]}}})
    m = FakeMsg()
    if attr == "photo":
        m.photo = [SimpleNamespace(file_id=fid)]
    else:
        setattr(m, attr, SimpleNamespace(file_id=fid))
    assert asyncio.run(admin_consume_media(aupd(1, m), ctx)) is True
    r = db.fetchone("SELECT cover_kind, cover_file_id FROM episodes WHERE id=?", (ep["id"],))
    assert (r["cover_kind"], r["cover_file_id"]) == (want, fid)
    assert "adm" not in ctx.user_data


def test_stray_media_gets_hint_not_silence(env):
    from bot.admin_handlers import admin_consume_media
    db, cfg, bot = env
    m = FakeMsg()
    m.voice = SimpleNamespace(file_id="VC9")
    u = aupd(1, m)
    assert asyncio.run(admin_consume_media(u, actx(db, cfg, bot))) is True
    assert any("اپیزودها" in t for t, _ in m.sent)


def test_stranger_media_silent(env):
    from bot.admin_handlers import admin_consume_media
    db, cfg, bot = env
    m = FakeMsg()
    m.video = SimpleNamespace(file_id="V9")
    u = aupd(999, m)
    assert asyncio.run(admin_consume_media(u, actx(db, cfg, bot))) is False
    assert m.sent == []


def test_voice_video_note_delivery(env):
    from bot.handlers import show_episode
    from modules.course_engine import get_course, set_episode_media
    from modules.users import get_or_create, set_phone, set_name
    db, cfg, bot = env
    u = get_or_create(db, 61, None)
    set_phone(db, u["id"], "09120000061")
    set_name(db, u["id"], "ن")
    c = get_course(db, "c")
    db.execute("UPDATE users SET current_course_id=? WHERE id=?", (c["id"], u["id"]))
    ep = db.fetchone("SELECT id FROM episodes WHERE episode_no=1")
    set_episode_media(db, ep["id"], "voice", "VC1")
    row = db.fetchone("SELECT * FROM users WHERE id=?", (u["id"],))
    asyncio.run(show_episode(aupd(61), actx(db, cfg, bot), row, c, 1))
    set_episode_media(db, ep["id"], "video_note", "VN1")
    asyncio.run(show_episode(aupd(61), actx(db, cfg, bot), row, c, 1))
    kinds = [k for k, _ in bot.calls]
    assert "voice" in kinds and "video_note" in kinds


def test_parse_bulk():
    from bot.admin_handlers import parse_bulk
    eps, errs = parse_bulk("1. اول | کپشن\nمتن یک\nمتن دو\n\n2. دوم\nمتن سه\n")
    assert errs == []
    assert [(e["no"], e["title"], e["caption"], len(e["parts"])) for e in eps] == [
        (1, "اول", "کپشن", 2), (2, "دوم", "", 1)]
    eps2, _ = parse_bulk("عنوان بدون شماره\nپارتش\n")
    assert eps2[0]["no"] >= 1 and eps2[0]["parts"] == ["پارتش"]
    _, errs3 = parse_bulk("0. بد\nمتن\n")
    assert errs3
    _, errs4 = parse_bulk("???\n")
    assert errs4


def test_bulk_save_flow(env):
    from bot.admin_handlers import admin_consume_text, do_bulk_save
    from modules.course_engine import get_episode
    db, cfg, bot = env
    ctx = actx(db, cfg, bot, {"adm": {"flow": "bulkep", "step": "text", "data": {}},
                              "adm_course": "c"})
    m = FakeMsg("5. تازه\nپارت یک\nپارت دو\n")
    assert asyncio.run(admin_consume_text(aupd(1, m), ctx)) is True
    assert ctx.user_data["adm"]["step"] == "confirm"
    u2 = aupd(1, query="adm:bulkok")
    asyncio.run(do_bulk_save(u2, ctx))
    ep = get_episode(db, "c", 5)
    assert ep and ep["caption"] == "پارت یک\n\nپارت دو"
    assert db.fetchone("SELECT COUNT(*) c FROM episode_parts WHERE episode_id=?", (ep["id"],))["c"] == 0
    assert any("قدم بعدی" in t for t, _ in u2.effective_message.sent)


def test_after_save_nav_buttons(env):
    from bot.admin_handlers import admin_consume_text
    db, cfg, bot = env
    ctx = actx(db, cfg, bot, {"adm": {"flow": "epadd", "step": "content",
                                      "data": {"title": "T9"}},
                              "adm_course": "c"})
    m = FakeMsg("متن اپیزود نه")
    asyncio.run(admin_consume_text(aupd(1, m), ctx))
    labels = [b.text for _, kb in m.sent if kb for row in kb.inline_keyboard for b in row]
    assert any("مشاهده اپیزود" in t for t in labels) and any("منوی مدیریت" in t for t in labels)


def test_course_delete_detaches(env):
    from modules.course_engine import delete_course
    from modules.offers import upsert_offer
    from modules.users import get_or_create
    db, cfg, bot = env
    c = db.fetchone("SELECT id FROM courses WHERE slug='c'")
    u = get_or_create(db, 62, None)
    db.execute("UPDATE users SET current_course_id=? WHERE id=?", (c["id"], u["id"]))
    upsert_offer(db, "cx", "T", "X", "https://x.test", "b", "always", course_id=c["id"])
    res = delete_course(db, c["id"])
    assert res["episodes"] == 1
    assert db.fetchone("SELECT current_course_id FROM users WHERE id=?", (u["id"],))["current_course_id"] is None
    assert db.fetchone("SELECT course_id FROM offers WHERE slug='cx'")["course_id"] is None
