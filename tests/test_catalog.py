"""Catalog, texts, purchase approval, settings, migrations, course CRUD."""
import asyncio
from pathlib import Path
import pytest
from modules.config import load_config
from modules.database import Database
from doubles import view_of

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def db(tmp_path):
    from modules.course_engine import seed_from_json
    d = Database(str(tmp_path / "k.db"))
    d.migrate()
    seed_from_json(d, "c1", {"title": "Course 1", "episodes": [
        {"no": 1, "title": "E1", "parts": [{"no": 1, "kind": "text", "text": "a"}]}]})
    seed_from_json(d, "c2", {"title": "Course 2", "episodes": [
        {"no": 1, "title": "E1", "parts": [{"no": 1, "kind": "text", "text": "b"}]}]})
    yield d
    d.close()


def test_migrations_apply(tmp_path):
    d = Database(str(tmp_path / "m.db"))
    d.migrate()
    ver = int(d.fetchone("SELECT value FROM settings WHERE key='schema_version'")["value"])
    assert ver >= 2
    cols = [r["name"] for r in d.fetchone("SELECT * FROM users LIMIT 0").keys()] if False else None
    import sqlite3
    info = d.conn.execute("PRAGMA table_info(users)").fetchall()
    assert "current_course_id" in [r[1] for r in info]
    info2 = d.conn.execute("PRAGMA table_info(offers)").fetchall()
    assert "course_id" in [r[1] for r in info2]
    d.close()


def test_settings_module(tmp_path):
    from modules.settings import all as sall, delete, get, set as sset
    d = Database(str(tmp_path / "s.db"))
    d.migrate()
    assert get(d, "nope") is None and get(d, "nope", "dflt") == "dflt"
    sset(d, "k", "v")
    assert get(d, "k") == "v" and sall(d)["k"] == "v"
    delete(d, "k")
    assert get(d, "k") is None
    d.close()


def test_text_override(db):
    from bot.texts import DEFAULTS, TEXT_DEFS, set_text, t
    assert t(db, "welcome") == DEFAULTS["welcome"]
    set_text(db, "welcome", "سلام سفارشی")
    assert t(db, "welcome") == "سلام سفارشی"
    assert {k for k, _, _ in TEXT_DEFS} <= set(DEFAULTS)


def test_catalog_isolates_progress(db):
    from modules.users import get_or_create
    from modules.progress import complete_part, progress_summary, unlocked_episode_no
    u = get_or_create(db, 701, None)
    complete_part(db, u["id"], "c1", 1, 1)
    assert progress_summary(db, u["id"], "c1")["done"] == 1
    assert progress_summary(db, u["id"], "c2")["done"] == 0
    assert unlocked_episode_no(db, u["id"], "c2") == 1


def test_course_crud_and_delete_cascade(db):
    from modules.course_engine import (create_course, delete_course, list_courses,
                                        set_course_active, get_course)
    c = create_course(db, "c3", "Course 3", "desc")
    assert get_course(db, "c3")["title"] == "Course 3"
    with pytest.raises(ValueError):
        create_course(db, "bad slug!", "X")
    set_course_active(db, c["id"], False)
    assert [x["slug"] for x in list_courses(db, only_active=True)] == ["c1", "c2"]
    res = delete_course(db, c["id"])
    assert res["episodes"] == 0 and get_course(db, "c3") is None
    # cascade: delete c1 removes its episodes/parts
    c1 = get_course(db, "c1")
    res = delete_course(db, c1["id"])
    assert res == {"episodes": 1, "parts": 1}
    assert db.fetchone("SELECT COUNT(*) c FROM episode_parts")["c"] == 1  # c2's part remains


def test_offer_scoping(db):
    from modules.offers import get_active_offer, upsert_offer
    c2 = db.fetchone("SELECT id FROM courses WHERE slug='c2'")
    g = upsert_offer(db, "glob", "G", "X", "https://x.test", "buy", "always")
    s = upsert_offer(db, "spec", "S", "X", "https://x.test", "buy", "always", course_id=c2["id"])
    assert get_active_offer(db, c2["id"])["slug"] == "spec"  # course offer wins
    assert get_active_offer(db, 999999)["slug"] in ("glob", "spec")  # falls back sane
    from modules.offers import delete_offer
    delete_offer(db, s["id"])
    assert get_active_offer(db, c2["id"])["slug"] == "glob"


def test_purchase_request_approve_decline(db):
    from modules.users import get_or_create
    from modules.offers import (approve_purchase, decline_purchase, pending_purchases,
                                 purchase_history, request_purchase, upsert_offer)
    u = get_or_create(db, 702, None)
    o = upsert_offer(db, "o9", "T", "X", "https://x.test", "buy", "always")
    r1 = request_purchase(db, u["id"], o["id"])
    r2 = request_purchase(db, u["id"], o["id"])
    assert r1["id"] == r2["id"] and r1["status"] == "pending"  # deduped
    assert len(pending_purchases(db)) == 1
    ok = approve_purchase(db, r1["id"])
    assert ok["status"] == "completed"
    assert db.fetchone("SELECT status FROM users WHERE id=?", (u["id"],))["status"] == "customer"
    assert approve_purchase(db, r1["id"]) is None  # already decided
    u2 = get_or_create(db, 703, None)
    r3 = request_purchase(db, u2["id"], o["id"])
    assert decline_purchase(db, r3["id"])["status"] == "declined"
    assert pending_purchases(db) == []
    assert len(purchase_history(db)) == 2


def test_episode_part_delete(db):
    from modules.course_engine import delete_episode, delete_part, get_episode, list_parts
    ep = get_episode(db, "c1", 1)
    assert delete_part(db, ep["id"], 1) is True
    assert list_parts(db, ep["id"]) == []
    delete_episode(db, ep["id"])
    assert get_episode(db, "c1", 1) is None


def test_filter_by_course(db):
    from modules.users import filter_by_stage, get_or_create
    from modules.progress import complete_part
    u = get_or_create(db, 704, None)
    db.execute("UPDATE users SET last_episode_id=(SELECT id FROM episodes WHERE course_id="
               "(SELECT id FROM courses WHERE slug='c1')), phone='09120000000' WHERE id=?", (u["id"],))
    got = filter_by_stage(db, "stuck_1", 0, "c1")
    assert any(x["id"] == u["id"] for x in got)
    assert not any(x["id"] == u["id"] for x in filter_by_stage(db, "stuck_1", 0, "c2"))



def test_seed_only_on_empty_db(tmp_path):
    from bot.main import seed_all
    from modules.config import load_config
    from modules.course_engine import create_course, get_course, list_courses
    cfg = load_config({})
    d = Database(str(tmp_path / "seed.db"))
    d.migrate()
    seed_all(d, cfg)
    assert list_courses(d) == []  # fresh installs start empty; admin builds via /admin
    # admin content must survive restarts
    create_course(d, "mine", "Mine")
    seed_all(d, cfg)
    assert [c["slug"] for c in list_courses(d)] == ["mine"]
    d.close()


def test_migration_004_merges_parts(tmp_path):
    from modules.course_engine import seed_from_json, get_episode
    d = Database(str(tmp_path / "m4.db"))
    d.migrate()
    seed_from_json(d, "c", {"title": "T", "episodes": [
        {"no": 1, "title": "E", "caption": "Intro",
         "parts": [{"no": 1, "kind": "text", "text": "P1"},
                   {"no": 2, "kind": "video", "text": "Cap", "file_id": "V9"}]}]})
    # simulate a pre-004 database, then apply only 004
    sql = (ROOT / "database" / "migrations" / "004_merge_parts.sql").read_text(encoding="utf-8")
    with d.conn:
        d.conn.executescript(sql)
    ep = get_episode(d, "c", 1)
    assert ep["caption"] == "Intro\n\nP1\n\nCap"
    assert (ep["cover_kind"], ep["cover_file_id"]) == ("video", "V9")
    d.close()


def test_select_course_callback(db):
    from bot.handlers import on_callback
    from modules.users import get_or_create, set_phone, set_name
    from doubles import FakeBot, make_ctx, make_update
    cfg = load_config({"ADMIN_IDS": "1", "COURSE_SLUG": "c1"})
    u = get_or_create(db, 705, None)
    set_phone(db, u["id"], "09120000003")
    set_name(db, u["id"], "ن")
    bot = FakeBot(chat_id=705)
    ctx = make_ctx(db, cfg, bot)
    w = make_update(705, query_data="course:c2", bot=bot)
    asyncio.run(on_callback(w, ctx))
    row = db.fetchone("SELECT current_course_id FROM users WHERE telegram_id=705")
    c2 = db.fetchone("SELECT id FROM courses WHERE slug='c2'")
    assert row["current_course_id"] == c2["id"]
    shown = view_of(w, bot)
    assert shown and "Course 2" in shown[0]
