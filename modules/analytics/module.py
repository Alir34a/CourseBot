"""Analytics computed from REAL events+progress. Never returns fake display-only numbers.

Denominators (all divide-by-zero guarded, timestamps UTC ISO8601):
- completion_rate: finished(users completing the max episode_no) / started(users starting episode 1)
- funnel churn per episode: (started-completed) / started_in_this_episode
- offer CTR: distinct clicked / distinct viewed; purchase rate: purchases / distinct viewed
- avg_time_to_purchase: mean(purchase.created_at - user.created_at) over completed purchases
"""
from __future__ import annotations


def funnel_by_episode(db, course_slug: str) -> list[dict]:
    from modules.course_engine import list_episodes
    eps = list_episodes(db, course_slug, only_active=False)
    out = []
    for ep in eps:
        no = int(ep["episode_no"])
        started = db.fetchone(
            "SELECT COUNT(DISTINCT user_id) c FROM user_episode_progress WHERE episode_id=?", (ep["id"],))
        completed = db.fetchone(
            "SELECT COUNT(DISTINCT user_id) c FROM user_episode_progress WHERE episode_id=? AND completed_at IS NOT NULL",
            (ep["id"],))
        s, c_ = int(started["c"]), int(completed["c"])
        out.append({"episode_no": no, "started": s, "completed": c_,
                    "drop": s - c_, "churn_pct": round((s - c_) / s * 100, 1) if s else 0.0})
    return out


def completion_rate(db, course_slug: str) -> dict:
    from modules.course_engine import list_episodes
    eps = list_episodes(db, course_slug, only_active=False)
    if not eps:
        return {"started": 0, "finished": 0, "pct": 0.0}
    first_id, last_no = eps[0]["id"], max(int(e["episode_no"]) for e in eps)
    started = int(db.fetchone(
        "SELECT COUNT(DISTINCT user_id) c FROM user_episode_progress WHERE episode_id=?", (first_id,))["c"])
    # users who completed the max episode_no (robust when nobody finished everything yet)
    last_ep = next((e for e in eps if int(e["episode_no"]) == last_no), None)
    finished = int(db.fetchone(
        "SELECT COUNT(*) c FROM user_episode_progress WHERE episode_id=? AND completed_at IS NOT NULL",
        (last_ep["id"],))["c"]) if last_ep else 0
    return {"started": started, "finished": finished,
            "pct": round(finished / started * 100, 1) if started else 0.0}


def offer_conversion(db, offer_id: int) -> dict:
    v = int(db.fetchone("SELECT COUNT(DISTINCT user_id) c FROM offer_interactions WHERE offer_id=? AND kind='viewed'", (offer_id,))["c"])
    c_ = int(db.fetchone("SELECT COUNT(DISTINCT user_id) c FROM offer_interactions WHERE offer_id=? AND kind='clicked'", (offer_id,))["c"])
    p = int(db.fetchone("SELECT COUNT(*) c FROM purchases WHERE offer_id=? AND status='completed'", (offer_id,))["c"])
    return {"viewed": v, "clicked": c_,
            "ctr_pct": round(c_ / v * 100, 1) if v else 0.0,
            "purchases": p, "purchase_rate_pct": round(p / v * 100, 1) if v else 0.0}


def avg_time_to_purchase(db) -> dict:
    rows = db.fetchall(
        """SELECT u.created_at AS start, p.created_at AS end FROM purchases p
           JOIN users u ON u.id=p.user_id WHERE p.status='completed'""")
    if not rows:
        return {"count": 0, "avg_hours": None}
    from datetime import datetime
    total = 0.0
    n = 0
    for r in rows:
        try:
            s = datetime.fromisoformat(r["start"]); e = datetime.fromisoformat(r["end"])
            total += (e - s).total_seconds() / 3600
            n += 1
        except Exception:
            continue
    return {"count": n, "avg_hours": round(total / n, 1) if n else None}


def dashboard_stats(db, course_slug: str) -> dict:
    total = int(db.fetchone("SELECT COUNT(*) c FROM users")["c"])
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).date().isoformat()
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    new_today = int(db.fetchone("SELECT COUNT(*) c FROM users WHERE substr(created_at,1,10)=?", (today,))["c"])
    new_month = int(db.fetchone("SELECT COUNT(*) c FROM users WHERE substr(created_at,1,7)=?", (month,))["c"])
    funnel = funnel_by_episode(db, course_slug)
    comp = completion_rate(db, course_slug)
    offers_rows = db.fetchall("SELECT id FROM offers WHERE is_active=1")
    offer_stats = [dict(id=r["id"], **offer_conversion(db, r["id"])) for r in offers_rows]
    return {"total_users": total, "new_today": new_today, "new_month": new_month,
            "funnel": funnel, "completion": comp, "offers": offer_stats,
            "avg_purchase": avg_time_to_purchase(db)}
