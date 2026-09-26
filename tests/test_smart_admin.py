"""Smart wizards: auto slug/numbers, kind auto-detect, part edit, episode cover."""
import asyncio
from types import SimpleNamespace
import pytest
from modules.config import load_config
from modules.database import Database
from doubles import FakeBot, FakeMsg, make_ctx, make_update


@pytest.fixture()
def env(tmp_path):
    from modules.course_engine import seed_from_json
    db = Database(str(tmp_path / "w.db"))
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


def test_auto_helpers():
    from modules.course_engine import auto_slug, next_episode_no, next_part_no
    import tempfile, os
    from modules.database import Database as D
    p = os.path.join(tempfile.gettempdir(), "auto-test.db")
    if os.path.exists(p):
        os.remove(p)
    d = D(p)
    d.migrate()
    from modules.course_engine import create_course, seed_from_json
    assert auto_slug(d) == "course-1"
    create_course(d, "course-1", "A")
    assert auto_slug(d) == "course-2"
    seed_from_json(d, "course-1", {"title": "A", "episodes": [
        {"no": 1, "title": "E", "parts": [{"no": 1, "kind": "text", "text": "x"},
                                          {"no": 2, "kind": "text", "text": "y"}]}]})
    assert next_episode_no(d, "course-1") == 2
    ep = d.fetchone("SELECT id FROM episodes WHERE episode_no=1")
    assert next_part_no(d, ep["id"]) == 3
    d.close()
    os.remove(p)


def test_courseadd_no_slug_question(env):
    from bot.admin_handlers import admin_consume_text
    from modules.course_engine import get_course
    db, cfg, bot = env
    ctx = actx(db, cfg, bot, {"adm": {"flow": "courseadd", "step": "title", "data": {}}})
    asyncio.run(admin_consume_text(aupd(1, FakeMsg("دوره تازه")), ctx))
    asyncio.run(admin_consume_text(aupd(1, FakeMsg("-")), ctx))
    assert "adm" not in ctx.user_data
    c = get_course(db, ctx.user_data.get("adm_course", "course-1"))
    assert c is not None and c["title"] == "دوره تازه"


def test_episode_text_edit_flow(env):
    from bot.admin_handlers import admin_consume_text
    db, cfg, bot = env
    ep = db.fetchone("SELECT id FROM episodes WHERE episode_no=1")
    ctx = actx(db, cfg, bot, {"adm": {"flow": "epedit", "step": "value",
                                      "data": {"ep_id": ep["id"], "field": "caption", "max": 4000}}})
    m = FakeMsg("متن تازه اپیزود")
    asyncio.run(admin_consume_text(aupd(1, m), ctx))
    assert "adm" not in ctx.user_data
    assert db.fetchone("SELECT caption FROM episodes WHERE id=?", (ep["id"],))["caption"] == "متن تازه اپیزود"
    assert any("مشاهده اپیزود" in t for t, kb in m.sent if kb
               for row in kb.inline_keyboard for b in row for t in [b.text])


def test_episode_title_edit_flow(env):
    from bot.admin_handlers import admin_consume_text
    db, cfg, bot = env
    ep = db.fetchone("SELECT id FROM episodes WHERE episode_no=1")
    ctx = actx(db, cfg, bot, {"adm": {"flow": "epedit", "step": "value",
                                      "data": {"ep_id": ep["id"], "field": "title", "max": 200}}})
    asyncio.run(admin_consume_text(aupd(1, FakeMsg("عنوان تازه")), ctx))
    assert db.fetchone("SELECT title FROM episodes WHERE id=?", (ep["id"],))["title"] == "عنوان تازه"


def test_cover_set_and_user_sees_it(env):
    from modules.course_engine import set_episode_media
    from bot.handlers import show_episode
    from modules.course_engine import get_course
    from modules.progress import complete_part
    from modules.users import get_or_create, set_phone, set_name
    db, cfg, bot = env
    u = get_or_create(db, 71, None)
    set_phone(db, u["id"], "09120000071")
    set_name(db, u["id"], "ن")
    c = get_course(db, "c")
    db.execute("UPDATE users SET current_course_id=? WHERE id=?", (c["id"], u["id"]))
    ep = db.fetchone("SELECT id FROM episodes WHERE episode_no=1")
    set_episode_media(db, ep["id"], "photo", "COV1")
    row = db.fetchone("SELECT * FROM users WHERE id=?", (u["id"],))
    asyncio.run(show_episode(aupd(71), actx(db, cfg, bot), row, c, 1))
    kinds = [k for k, _ in bot.calls]
    assert "photo" in kinds and bot.calls[0][1] == "COV1"


def test_epadd_text_and_media_branches(env):
    from bot.admin_handlers import admin_consume_media, admin_consume_text
    from modules.course_engine import get_episode
    db, cfg, bot = env
    # text-first branch: title -> content(text) -> saved, no video
    ctx = actx(db, cfg, bot, {"adm": {"flow": "epadd", "step": "title", "data": {}},
                              "adm_course": "c"})
    asyncio.run(admin_consume_text(aupd(1, FakeMsg("اپیزود متنی")), ctx))
    asyncio.run(admin_consume_text(aupd(1, FakeMsg("متن کامل اپیزود")), ctx))
    assert "adm" not in ctx.user_data
    ep = get_episode(db, "c", 2)
    assert ep["caption"] == "متن کامل اپیزود" and not ep["cover_file_id"]
    # media branch: title -> content(media) -> desc -> saved with media
    ctx2 = actx(db, cfg, bot, {"adm": {"flow": "epadd", "step": "title", "data": {}},
                               "adm_course": "c"})
    asyncio.run(admin_consume_text(aupd(1, FakeMsg("اپیزود تصویری")), ctx2))
    m = FakeMsg()
    m.video = SimpleNamespace(file_id="EV1")
    asyncio.run(admin_consume_media(aupd(1, m), ctx2))
    assert ctx2.user_data["adm"]["step"] == "desc"
    asyncio.run(admin_consume_text(aupd(1, FakeMsg("توضیح زیر ویدیو")), ctx2))
    ep3 = get_episode(db, "c", 3)
    assert (ep3["cover_kind"], ep3["cover_file_id"]) == ("video", "EV1")
    assert ep3["caption"] == "توضیح زیر ویدیو"


def test_open_counts_as_seen_and_next_button(env):
    from bot.handlers import show_episode
    from modules.course_engine import get_course
    from modules.events import count_by_type
    db, cfg, bot = env
    from modules.users import get_or_create, set_phone, set_name
    u = get_or_create(db, 72, None)
    set_phone(db, u["id"], "09120000072")
    set_name(db, u["id"], "ن")
    c = get_course(db, "c")
    db.execute("UPDATE users SET current_course_id=? WHERE id=?", (c["id"], u["id"]))
    row = db.fetchone("SELECT * FROM users WHERE id=?", (u["id"],))
    w = aupd(72, query="ep:1")
    asyncio.run(show_episode(w, actx(db, cfg, bot), row, c, 1))
    # entering auto-completed the episode
    assert db.fetchone("SELECT completed_at FROM user_episode_progress WHERE user_id=?",
                       (u["id"],))["completed_at"]
    n1 = count_by_type(db, "episode_completed")
    # re-entry must not duplicate completion events
    w2 = aupd(72, query="ep:1")
    asyncio.run(show_episode(w2, actx(db, cfg, bot), row, c, 1))
    assert count_by_type(db, "episode_completed") == n1


def test_media_only_episode_completes_on_entry(env):
    from bot.handlers import show_episode
    from modules.course_engine import get_course, set_episode_media
    from modules.users import get_or_create, set_phone, set_name
    db, cfg, bot = env
    u = get_or_create(db, 73, None)
    set_phone(db, u["id"], "09120000073")
    set_name(db, u["id"], "ن")
    c = get_course(db, "c")
    db.execute("UPDATE users SET current_course_id=? WHERE id=?", (c["id"], u["id"]))
    # episode 1 here has 1 part; complete it, add a partless episode 2 and enter it
    from modules.course_engine import upsert_episode
    from modules.progress import complete_part
    upsert_episode(db, "c", 2, "E2", "")
    complete_part(db, u["id"], "c", 1, 1)
    row = db.fetchone("SELECT * FROM users WHERE id=?", (u["id"],))
    w = aupd(73, query="ep:2")
    asyncio.run(show_episode(w, actx(db, cfg, bot), row, c, 2))
    from modules.progress import progress_summary
    assert progress_summary(db, u["id"], "c")["done"] == 2


def test_episode_admin_detail_has_edit_buttons(env):
    from bot.admin_handlers import show_episode_detail
    db, cfg, bot = env
    ep = db.fetchone("SELECT id FROM episodes WHERE episode_no=1")
    w = aupd(1, query="adm:ep:1")
    asyncio.run(show_episode_detail(w, actx(db, cfg, bot), ep["id"]))
    labels = [b.text for t, kb in w.callback_query.edited for row_ in kb.inline_keyboard for b in row_]
    assert any("ویرایش عنوان" in t for t in labels) and any("ویرایش متن" in t for t in labels)
    from bot.admin_handlers import admin_consume_media
    db, cfg, bot = env
    ep = db.fetchone("SELECT id FROM episodes WHERE episode_no=1")
    ctx = actx(db, cfg, bot, {"adm": {"flow": "mediaadd", "step": "media",
                                      "data": {"ep_id": ep["id"]}}})
    m = FakeMsg()
    m.photo = [SimpleNamespace(file_id="COV9")]
    assert asyncio.run(admin_consume_media(aupd(1, m), ctx)) is True
    r = db.fetchone("SELECT cover_kind, cover_file_id FROM episodes WHERE id=?", (ep["id"],))
    assert (r["cover_kind"], r["cover_file_id"]) == ("photo", "COV9")
    assert "adm" not in ctx.user_data
