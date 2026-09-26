"""Config/owner hygiene + event resilience + analytics denominators + backup."""
import re
from pathlib import Path
import pytest
from modules.config import is_owner_configured, load_config
from modules.database import Database

ROOT = Path(__file__).resolve().parents[1]


def test_defaults_are_unconfigured():
    cfg = load_config({})
    assert is_owner_configured(cfg) == {"bot_token": False, "admin_ids": False, "owner_email": False}
    assert cfg.admin_ids == ()


def test_admin_ids_parsing():
    cfg = load_config({"ADMIN_IDS": "111, 222;333"})
    assert cfg.admin_ids == (111, 222, 333)


def test_no_hardcoded_owner_secrets_in_source():
    """Sentinel strings may only live in config/.env.example and the sentinel table."""
    hits = []
    for p in list((ROOT / "modules").rglob("*.py")) + list((ROOT / "bot").rglob("*.py")):
        text = p.read_text(encoding="utf-8")
        if "PUT_YOUR_BOT_TOKEN_HERE" in text or "owner@example.com" in text:
            hits.append(p.relative_to(ROOT).as_posix())
    assert hits == ["modules/config/module.py"], hits
    assert not (ROOT / "admin_panel").exists(), "web panel must stay deleted"


def test_env_example_and_no_real_env_in_repo():
    assert (ROOT / "config" / ".env.example").exists()
    example = (ROOT / "config" / ".env.example").read_text(encoding="utf-8")
    assert "PUT_YOUR_BOT_TOKEN_HERE" in example
    # .env may exist as a local developer copy, but it must ALWAYS be
    # git-ignored so real secrets can never be committed.
    import subprocess
    r = subprocess.run(["git", "check-ignore", "-q", ".env"], cwd=ROOT)
    assert r.returncode == 0, ".env must be git-ignored"


def test_track_never_breaks_flow():
    from modules.events import track
    class Broken:
        def execute(self, *a, **k):
            raise RuntimeError("db down")
    assert track(Broken(), 1, "episode_started") == 0  # no raise


def test_progress_survives_event_store_failure(tmp_path):
    from modules.course_engine import seed_from_json
    from modules.users import get_or_create
    from modules.progress import complete_part, progress_summary
    db = Database(str(tmp_path / "r.db"))
    db.migrate()
    seed_from_json(db, "c", {"title": "T", "episodes": [
        {"no": 1, "title": "E1", "parts": [{"no": 1, "kind": "text", "text": "x"}]}]})
    db.execute("DROP TABLE events")  # event store gone
    u = get_or_create(db, 999, None)
    # get_or_create's internal track() must not raise either
    res = complete_part(db, u["id"], "c", 1, 1)
    assert res["episode_completed"] is True
    assert progress_summary(db, u["id"], "c")["done"] == 1
    db.close()


def test_analytics_empty_denominators(tmp_path):
    from modules.course_engine import seed_from_json
    from modules.analytics import completion_rate, funnel_by_episode, offer_conversion, avg_time_to_purchase
    from modules.offers import upsert_offer
    db = Database(str(tmp_path / "a.db"))
    db.migrate()
    seed_from_json(db, "c", {"title": "T", "episodes": [
        {"no": 1, "title": "E1", "parts": [{"no": 1, "kind": "text", "text": "x"}]}]})
    assert completion_rate(db, "c") == {"started": 0, "finished": 0, "pct": 0.0}
    assert funnel_by_episode(db, "c")[0]["churn_pct"] == 0.0
    o = upsert_offer(db, "o", "T", "X", "https://x.test", "buy", "always")
    conv = offer_conversion(db, o["id"])
    assert conv["ctr_pct"] == 0.0 and conv["purchase_rate_pct"] == 0.0
    assert avg_time_to_purchase(db) == {"count": 0, "avg_hours": None}
    db.close()


def test_phone_normalization_edges():
    from modules.phone_verification import normalize_ir_mobile
    assert normalize_ir_mobile("+989121234567") == "09121234567"
    assert normalize_ir_mobile("989121234567") == "09121234567"
    assert normalize_ir_mobile("09121234567") == "09121234567"
    assert normalize_ir_mobile("0912") is None
    assert normalize_ir_mobile("") is None


def test_purchase_webhook_secret_enforced(tmp_path):
    from modules.users import get_or_create
    from modules.offers import record_purchase
    db = Database(str(tmp_path / "w.db"))
    db.migrate()
    u = get_or_create(db, 313, None)
    with pytest.raises(PermissionError):
        record_purchase(db, u["id"], None, secret="wrong", expected_secret="right")
    db.close()


def test_backup_and_restore_roundtrip(tmp_path):
    from modules.backup import backup, list_backups, restore_to
    from modules.users import get_or_create
    live = str(tmp_path / "live.db")
    db = Database(live)
    db.migrate()
    get_or_create(db, 4242, None)
    db.close()
    snap = backup(live, str(tmp_path / "snaps"))
    assert list_backups(live) == []  # custom dir, default dir untouched
    assert Path(snap).exists()
    with pytest.raises(RuntimeError):
        restore_to(snap, live, require_stopped=True)  # safety gate
    assert restore_to(snap, live, require_stopped=False) == live
    db2 = Database(live)
    assert db2.fetchone("SELECT telegram_id FROM users WHERE telegram_id=4242")
    db2.close()
