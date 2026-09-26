"""Coverage: new-user flow, progress gating, anti-bypass, analytics, admin, scale."""
import json
import pytest
from modules.database import Database


@pytest.fixture()
def db(tmp_path):
    d = Database(str(tmp_path / "t.db"))
    d.migrate()
    yield d
    d.close()


@pytest.fixture()
def course(db):
    from modules.course_engine import seed_from_json
    data = {"title": "T", "description": "", "episodes": [
        {"no": i, "title": f"Ep {i}", "caption": "",
         "parts": [{"no": 1, "kind": "text", "text": f"e{i}p1"},
                   {"no": 2, "kind": "text", "text": f"e{i}p2"}]} for i in (1, 2, 3)]}
    seed_from_json(db, "test-course", data)
    return "test-course"


def test_new_user_phone_name_flow(db):
    from modules.users import get_or_create, get_by_telegram
    from modules.phone_verification import normalize_ir_mobile, validate_and_save
    u = get_or_create(db, 111, "ali")
    assert u["status"] == "new" and u["phone"] is None
    assert normalize_ir_mobile("0912 345 6789") == "09123456789"
    assert normalize_ir_mobile("not-a-number") is None
    ok, phone = validate_and_save(db, u["id"], "09123456789", 111, 111)
    assert ok and phone == "09123456789"
    # spoofed contact (someone else's number) must be rejected
    ok2, _ = validate_and_save(db, u["id"], "09123456789", 999, 111)
    assert not ok2
    from modules.users import set_name
    u2 = set_name(db, u["id"], "علی رضایی")
    assert u2["full_name"] == "علی رضایی"
    assert get_by_telegram(db, 111)["status"] == "in_course"


def test_progress_sequential_and_gating(db, course):
    from modules.users import get_or_create
    from modules.progress import (can_access_episode, can_access_part, complete_part,
                                  progress_summary, unlocked_episode_no)
    u = get_or_create(db, 222, None)
    assert unlocked_episode_no(db, u["id"], course) == 1
    assert can_access_episode(db, u["id"], course, 1)
    assert not can_access_episode(db, u["id"], course, 2)
    assert not can_access_part(db, u["id"], course, 1, 2)  # part2 before part1
    assert can_access_part(db, u["id"], course, 1, 1)
    r = complete_part(db, u["id"], course, 1, 1)
    assert r["episode_completed"] is False
    assert can_access_part(db, u["id"], course, 1, 2)
    r = complete_part(db, u["id"], course, 1, 2)
    assert r["episode_completed"] is True
    assert unlocked_episode_no(db, u["id"], course) == 2
    s = progress_summary(db, u["id"], course)
    assert (s["done"], s["total"]) == (1, 3)


def test_anti_bypass(db, course):
    from modules.users import get_or_create
    from modules.progress import complete_part
    from modules.telegram_core import validate_callback
    u = get_or_create(db, 333, None)
    with pytest.raises(PermissionError):
        complete_part(db, u["id"], course, 3, 1)  # locked episode
    with pytest.raises(PermissionError):
        complete_part(db, u["id"], course, 1, 2)  # skipping part 1
    assert validate_callback("ep:2")
    assert validate_callback("done:1:2")
    assert not validate_callback("ep:2; DROP TABLE users--")
    assert not validate_callback("__import__('os').system('x')")
    assert not validate_callback("x" * 200)


def test_analytics_events(db, course):
    from modules.users import get_or_create
    from modules.progress import complete_part
    from modules.analytics import funnel_by_episode, completion_rate, offer_conversion
    from modules.offers import upsert_offer, log_interaction, record_purchase
    u = get_or_create(db, 444, None)
    complete_part(db, u["id"], course, 1, 1)
    complete_part(db, u["id"], course, 1, 2)
    funnel = funnel_by_episode(db, course)
    ep1 = next(f for f in funnel if f["episode_no"] == 1)
    assert ep1["started"] == 1 and ep1["completed"] == 1
    comp = completion_rate(db, course)
    assert comp["started"] == 1
    offer = upsert_offer(db, "o1", "T", "Txt", "https://x.test", "buy", "episode:1")
    log_interaction(db, u["id"], offer["id"], "viewed")
    log_interaction(db, u["id"], offer["id"], "clicked")
    record_purchase(db, u["id"], offer["id"], amount=1000, expected_secret="")
    conv = offer_conversion(db, offer["id"])
    assert conv["viewed"] == 1 and conv["clicked"] == 1 and conv["purchases"] == 1
    assert conv["ctr_pct"] == 100.0


def test_admin_dashboard_and_user_detail(db, course):
    from modules.admin import dashboard, user_detail
    from modules.users import get_or_create
    from modules.progress import complete_part
    u = get_or_create(db, 606, None)
    complete_part(db, u["id"], course, 1, 1)
    s = dashboard(db, course)
    assert {"total_users", "funnel", "completion"} <= set(s)
    d = user_detail(db, u["id"])
    assert d["telegram_id"] == 606 and d["episodes"] and "course_title" in d["episodes"][0]
    assert any(e["type"] == "episode_part_completed" for e in d["timeline"])


def test_scale_1100_users(db, course):
    from modules.users import get_or_create
    for i in range(1100):
        get_or_create(db, 10_000 + i, None)
    n = db.fetchone("SELECT COUNT(*) c FROM users")["c"]
    assert n >= 1100
    from modules.analytics import funnel_by_episode
    assert isinstance(funnel_by_episode(db, course), list)
    idx = db.fetchall("SELECT name FROM sqlite_master WHERE type='index'")
    names = {r["name"] for r in idx}
    assert "idx_events_type_time" in names and "idx_uep_user" in names
