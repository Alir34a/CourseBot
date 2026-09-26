"""Telegram admin console: the full panel inside the bot, ADMIN_IDS only.

Thin presentation over the same modules/* — no business logic duplicated here.
Non-admins get silence (panel existence is not leaked).
Browsing context: ctx.user_data['adm_course'] = course slug the admin currently manages.
"""
from __future__ import annotations
import re
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

import bot.admin_texts as A
from modules.admin import user_detail
from modules.analytics import dashboard_stats
from modules.course_engine import (auto_slug, course_stats, create_course, delete_course, delete_episode,
                                    get_course, get_episode, list_courses, list_episodes,
                                    set_course_active, upsert_episode)
from modules.database import Database
from modules.logging_mod import get_logger
from modules.messaging import audience_ids, queue_message
from modules.offers import (approve_purchase, decline_purchase, delete_offer,
                             list_offers, pending_purchases, purchase_history, upsert_offer)
from modules.telegram_core import (EDITED, UNCHANGED, is_admin, parse_callback, safe_edit,
                                   validate_callback)

from modules.users import filter_by_stage, search

log = get_logger("admin_bot")

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,60}$")
STAGES = ["registered_only", "not_started", "finished", "customers",
          "offer_viewed", "offer_clicked", "inactive"]
KIND_FA = {"text": "متن", "video": "ویدیو", "photo": "عکس", "audio": "صوت",
           "voice": "ویس", "video_note": "ویدیو دایره‌ای", "file": "فایل"}


# ---------- pure validation helpers (unit-tested) ----------

def v_ep_no(raw: str) -> int:
    v = int(str(raw).strip())
    if not 1 <= v <= 500:
        raise ValueError("range")
    return v


def v_slug(raw: str) -> str:
    s = str(raw or "").strip()
    if not SLUG_RE.match(s):
        raise ValueError("slug")
    return s


def v_url(raw: str) -> str:
    s = str(raw or "").strip()
    if not s.startswith(("https://", "http://")) or len(s) > 500:
        raise ValueError("url")
    return s


def v_trigger(raw: str) -> str:
    s = str(raw or "").strip()
    if s != "always" and not re.match(r"^episode:\d{1,3}$", s):
        raise ValueError("trigger")
    return s


# ---------- gating ----------

def _db(ctx: ContextTypes.DEFAULT_TYPE) -> Database:
    return ctx.application.bot_data["db"]


def _cfg(ctx):
    return ctx.application.bot_data["cfg"]


def is_admin_update(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> bool:
    u = update.effective_user
    return bool(u) and is_admin(u.id, _cfg(ctx).admin_ids)


def admin_required(func):
    async def wrapper(update: Update, ctx: ContextTypes.DEFAULT_TYPE, *a, **kw):
        if not is_admin_update(update, ctx):
            try:
                if update.callback_query:
                    await update.callback_query.answer()
            except Exception:
                pass
            return  # silent: don't leak panel existence
        return await func(update, ctx, *a, **kw)
    return wrapper


def _adm_state(ctx: ContextTypes.DEFAULT_TYPE) -> dict | None:
    return ctx.user_data.get("adm")


def _set_adm(ctx, flow: str, step: str, data: dict | None = None) -> None:
    ctx.user_data["adm"] = {"flow": flow, "step": step, "data": data or {}}


def _clear_adm(ctx) -> None:
    ctx.user_data.pop("adm", None)


async def _saved_nav(msg, rows: list) -> None:
    """Every wizard ends with next-step buttons — never a dead end."""
    rows = [list(r) for r in rows] + [[InlineKeyboardButton(A.BTN_BACK_MENU, callback_data="adm:menu")]]
    await msg.reply_text(A.SAVED_NEXT, reply_markup=InlineKeyboardMarkup(rows))


# ---------- rendering ----------

def menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(A.BTN_STATS, callback_data="adm:stats"),
         InlineKeyboardButton(A.BTN_USERS, callback_data="adm:users")],
        [InlineKeyboardButton("📚 دوره‌ها", callback_data="adm:courses"),
         InlineKeyboardButton(A.BTN_EPS, callback_data="adm:eps")],
        [InlineKeyboardButton(A.BTN_OFFERS, callback_data="adm:offers"),
         InlineKeyboardButton("💰 خریدها", callback_data="adm:pays")],
        [InlineKeyboardButton(A.BTN_MSG, callback_data="adm:msg"),
         InlineKeyboardButton("📝 متن‌ها", callback_data="adm:texts")],
        [InlineKeyboardButton(A.BTN_ANALYTICS, callback_data="adm:analytics")],
    ])


def _browse_course(db, ctx) -> dict | None:
    """Course the admin is currently managing (defaults to first course)."""
    slug = ctx.user_data.get("adm_course")
    if slug:
        c = get_course(db, slug)
        if c:
            return c
    courses = list_courses(db, only_active=False)
    if courses:
        ctx.user_data["adm_course"] = courses[0]["slug"]
        return courses[0]
    return None


def _back_kb(extra: list | None = None) -> InlineKeyboardMarkup:
    rows = extra or []
    rows.append([InlineKeyboardButton(A.BTN_BACK_MENU, callback_data="adm:menu")])
    return InlineKeyboardMarkup(rows)


async def _view(q, text: str, reply_markup=None) -> None:
    """Show an admin screen on the message the button lives on.

    UNCHANGED (re-tapping the button of the screen already on screen) is a
    success, not a fault. If the target turns out to be unusable, post a fresh
    copy: the panel must never leave the admin staring at nothing.
    """
    status = await safe_edit(q, text, reply_markup=reply_markup)
    if status in (EDITED, UNCHANGED):
        return
    try:
        await q.message.reply_text(text, reply_markup=reply_markup)
    except Exception:
        log.warning("admin screen fallback failed")


async def _send_menu(update: Update, ctx, edit: bool = False) -> None:
    if edit and update.callback_query:
        try:
            await update.callback_query.answer()
            await _view(update.callback_query, A.MENU_TITLE, reply_markup=menu_kb())
            return
        except Exception:
            pass
    await update.effective_message.reply_text(A.MENU_TITLE, reply_markup=menu_kb())



def stats_text(db: Database, course_slug: str) -> str:
    s = dashboard_stats(db, course_slug)
    lines = [A.STATS_TITLE,
             "عددها زنده‌اند: کاربران، تکمیل دوره و ریزش هر اپیزود.",
             f"👥 کل: {s['total_users']} | امروز: {s['new_today']} | این ماه: {s['new_month']}",
             f"✅ تکمیل: {s['completion']['finished']} از {s['completion']['started']} ({s['completion']['pct']}٪)"]
    for f in s["funnel"]:
        lines.append(f"Ep{f['episode_no']}: شروع {f['started']}، تکمیل {f['completed']} (ریزش {f['drop']})")
    for o in s["offers"]:
        lines.append(f"🎁 آفر{o['id']}: دیده {o['viewed']}، کلیک {o['clicked']} ({o['ctr_pct']}٪)، خرید {o['purchases']}")
    avg = s["avg_purchase"]
    lines.append("⏱ تا خرید: " + ("—" if avg.get("avg_hours") is None
                                  else f"{avg['avg_hours']} ساعت روی {avg['count']} خرید"))
    return "\n".join(lines)


def user_line(u: dict) -> str:
    return (f"{u.get('full_name') or '—'} | {u.get('phone') or '—'} | "
            f"{A.STATUS_FA.get(str(u.get('status')), u.get('status'))}")


# ---------- views ----------

@admin_required
async def cmd_admin(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    _clear_adm(ctx)
    await _send_menu(update, ctx)


async def show_stats(update: Update, ctx) -> None:
    q = update.callback_query
    await q.answer()
    c = _browse_course(_db(ctx), ctx)
    slug = c["slug"] if c else _cfg(ctx).course_slug
    await _view(q, stats_text(_db(ctx), slug), reply_markup=_back_kb())


async def show_users(update: Update, ctx) -> None:
    db = _db(ctx)
    q = update.callback_query
    await q.answer()
    c = _browse_course(db, ctx)
    cslug = c["slug"] if c else None
    total = db.fetchone("SELECT COUNT(*) c FROM users")["c"]
    rows = [[InlineKeyboardButton("🔍 جست‌وجو", callback_data="adm:usersearch")]]
    for st in STAGES:
        n = len(filter_by_stage(db, st, 3, cslug))
        rows.append([InlineKeyboardButton(f"{A.STAGE_NAMES[st]} ({n})", callback_data=f"adm:stage:{st}")])
    await _view(q, f"{A.USERS_TITLE}\nکل: {total} نفر\n(فیلترهای مرحله‌ای برای دوره: {c['title'] if c else '—'})\nفیلتر را انتخاب کن یا جست‌وجو بزن:",
                              reply_markup=_back_kb(rows))


async def show_user_detail(update: Update, ctx, uid: int) -> None:
    db = _db(ctx)
    q = update.callback_query
    u = user_detail(db, uid)
    if not u:
        await q.answer("کاربر پیدا نشد.", show_alert=True)
        return
    await q.answer()
    eps = "\n".join(f"Ep{e['episode_no']}: {'✅' if e['completed_at'] else '…'} {e['title']}" for e in u["episodes"][:15]) or "هنوز وارد دوره نشده"
    tls = "\n".join(f"• {e['type']} — {e['created_at'][:16]}" for e in u["timeline"][:10])
    txt = (f"👤 {u.get('full_name') or '—'}\n📱 {u.get('phone') or '—'} | 🆔 {u['telegram_id']}\n"
           f"وضعیت: {A.STATUS_FA.get(str(u['status']), u['status'])}\nآخرین فعالیت: {u.get('last_activity_at') or '—'}\n\n"
           f"{eps}\n\n{tls}")
    await _view(q, txt[:4000], reply_markup=_back_kb([[
        InlineKeyboardButton("👥 لیست کاربران", callback_data="adm:users")]]))


async def show_episodes(update: Update, ctx) -> None:
    db = _db(ctx)
    q = update.callback_query
    await q.answer()
    c = _browse_course(db, ctx)
    if not c:
        await _view(q, "هنوز دوره‌ای ساخته نشده. اول از «📚 دوره‌ها» بساز.",
                                  reply_markup=_back_kb())
        return
    eps = list_episodes(db, c["slug"], only_active=False)
    rows = [[InlineKeyboardButton(f"{'✅' if e['is_active'] else '⏸'} Ep{e['episode_no']} {e['title']}",
                                 callback_data=f"adm:ep:{e['id']}")] for e in eps]
    rows.append([InlineKeyboardButton("➕ اپیزود جدید", callback_data="adm:epadd")])
    rows.append([InlineKeyboardButton("📥 ساخت گروهی با متن", callback_data="adm:bulk")])
    await _view(q, f"{A.EPS_TITLE}\nدوره: {c['title']}\nبرای ویرایش روی هر اپیزود بزن:",
                              reply_markup=_back_kb(rows))


async def show_episode_detail(update: Update, ctx, ep_id: int) -> None:
    db = _db(ctx)
    q = update.callback_query
    ep = db.fetchone("SELECT e.*, c.title AS course_title, c.slug AS course_slug FROM episodes e "
                     "JOIN courses c ON c.id=e.course_id WHERE e.id=?", (ep_id,))
    if not ep:
        await q.answer("اپیزود پیدا نشد.", show_alert=True)
        return
    await q.answer()
    cover_line = f"🎬 رسانه: {KIND_FA.get(ep['cover_kind'], ep['cover_kind'])}" if ep["cover_file_id"] else "🎬 رسانه: ندارد"
    cap = (ep["caption"] or "")[:200] or "—"
    rows = [
        [InlineKeyboardButton("✏️ ویرایش عنوان", callback_data=f"adm:eptitle:{ep['id']}"),
         InlineKeyboardButton("✏️ ویرایش متن", callback_data=f"adm:eptext:{ep['id']}")],
        [InlineKeyboardButton("🎬 گذاشتن رسانه" if not ep["cover_file_id"] else "🎬 عوض‌کردن رسانه",
                              callback_data=f"adm:media:{ep['id']}")] +
        ([InlineKeyboardButton("❌ حذف رسانه", callback_data=f"adm:mediadel:{ep['id']}")] if ep["cover_file_id"] else []),
        [InlineKeyboardButton("غیرفعال کن" if ep["is_active"] else "فعال کن",
                              callback_data=f"adm:eptoggle:{ep['id']}"),
         InlineKeyboardButton("↑", callback_data=f"adm:epmove:{ep['id']}:-1"),
         InlineKeyboardButton("↓", callback_data=f"adm:epmove:{ep['id']}:1")],
        [InlineKeyboardButton("🗑 حذف اپیزود", callback_data=f"adm:epdel:{ep['id']}")],
        [InlineKeyboardButton("📺 لیست اپیزودها", callback_data="adm:eps")],
    ]
    await safe_edit(q,
        f"Ep{ep['episode_no']} {ep['title']}\n({ep['course_title']})\n{cover_line}\n\nمتن:\n{cap}",
        reply_markup=_back_kb(rows))


async def _save_ep_field(update: Update, ctx, ep_id: int, field: str, value: str) -> None:
    db = _db(ctx)
    if field == "title":
        db.execute("UPDATE episodes SET title=? WHERE id=?", (value[:200], ep_id))
    else:
        db.execute("UPDATE episodes SET caption=? WHERE id=?", (value[:4000], ep_id))
    _clear_adm(ctx)
    await update.effective_message.reply_text(A.SAVED)
    # refresh view if invoked from a callback message, else just confirm
    if update.callback_query:
        try:
            await show_episode_detail(update, ctx, ep_id)
            return
        except Exception:
            pass
    await _saved_nav(update.effective_message, [
        [InlineKeyboardButton("🧩 مشاهده اپیزود", callback_data=f"adm:ep:{ep_id}")]])


async def show_offers(update: Update, ctx) -> None:
    from modules.analytics import offer_conversion
    db = _db(ctx)
    q = update.callback_query
    await q.answer()
    c = _browse_course(db, ctx)
    rows_db = list_offers(db, c["id"] if c else None)
    lines, kb_rows = [], []
    for o in rows_db:
        conv = offer_conversion(db, o["id"])
        scope = "🌍 همه" if not o.get("course_id") else (c["title"] if c and o.get("course_id") == c["id"] else "دوره دیگر")
        lines.append(f"{'✅' if o['is_active'] else '⏸'} {o['title']} ({o['trigger_rule']}) [{scope}]\n"
                     f"دیده {conv['viewed']} | کلیک {conv['clicked']} ({conv['ctr_pct']}٪) | خرید {conv['purchases']}")
        kb_rows.append([InlineKeyboardButton(
            f"{'غیرفعال' if o['is_active'] else 'فعال'}: {o['slug']}", callback_data=f"adm:offtoggle:{o['id']}"),
            InlineKeyboardButton("🗑", callback_data=f"adm:offdel:{o['id']}")])
    kb_rows.append([InlineKeyboardButton("➕ پیشنهاد جدید", callback_data="adm:offadd")])
    await _view(q, f"{A.OFFERS_TITLE}\nدوره: {c['title'] if c else '—'} (+ سراسری‌ها)\n"
                              "پیشنهاد همان پیامی است که موقع مناسب به کاربر نشان داده می‌شود.\n\n" + ("\n\n".join(lines) if lines else "پیشنهادی نیست."),
                              reply_markup=_back_kb(kb_rows))


async def do_delete_offer(update: Update, ctx, oid: int) -> None:
    delete_offer(_db(ctx), oid)
    await update.callback_query.answer("حذف شد.")
    await show_offers(update, ctx)


async def show_msg(update: Update, ctx) -> None:
    db = _db(ctx)
    q = update.callback_query
    await q.answer()
    rows = [dict(r) for r in db.fetchall("SELECT * FROM outbox_messages ORDER BY id DESC LIMIT 8")]
    fa = {"pending": "⏳ در صف", "sent": "✅ ارسال شد", "failed": "❌ ناموفق"}
    hist = "\n".join(f"#{m['id']} {fa.get(m['status'], m['status'])}: {(m['text'] or '')[:50]}" for m in rows) or "صفی نیست"
    kb = [[InlineKeyboardButton("✉️ پیام جدید", callback_data="adm:msgaud:ask")]]
    await _view(q, f"{A.MSG_TITLE}\n\nتاریخچه:\n{hist}", reply_markup=_back_kb(kb))


async def show_analytics(update: Update, ctx) -> None:
    q = update.callback_query
    await q.answer()
    c = _browse_course(_db(ctx), ctx)
    slug = c["slug"] if c else _cfg(ctx).course_slug
    s = dashboard_stats(_db(ctx), slug)
    lines = [A.ANALYTICS_TITLE, f"تکمیل دوره: {s['completion']['pct']}٪",
             "٪ ریزش هر اپیزود:"]
    lines += [f"Ep{f['episode_no']}: {f['churn_pct']}٪" for f in s["funnel"]]
    await _view(q, "\n".join(lines), reply_markup=_back_kb())


# ---------- mutations ----------

async def do_toggle_episode(update: Update, ctx, eid: int) -> None:
    db = _db(ctx)
    r = db.fetchone("SELECT is_active FROM episodes WHERE id=?", (eid,))
    if r:
        db.execute("UPDATE episodes SET is_active=? WHERE id=?", (0 if r["is_active"] else 1, eid))
    await update.callback_query.answer(A.TOGGLED)
    await show_episode_detail(update, ctx, eid)


async def do_move_episode(update: Update, ctx, eid: int, d: int) -> None:
    db = _db(ctx)
    cur = db.fetchone("SELECT course_id FROM episodes WHERE id=?", (eid,))
    if cur:
        rows = db.fetchall("SELECT id, sort_order FROM episodes WHERE course_id=? ORDER BY sort_order, episode_no",
                           (cur["course_id"],))
        ids = [r["id"] for r in rows]
        i, j = ids.index(eid), ids.index(eid) + d
        if 0 <= j < len(ids):
            a, b = rows[i], rows[j]
            db.execute("UPDATE episodes SET sort_order=? WHERE id=?", (b["sort_order"], a["id"]))
            db.execute("UPDATE episodes SET sort_order=? WHERE id=?", (a["sort_order"], b["id"]))
    await update.callback_query.answer(A.MOVED)
    await show_episode_detail(update, ctx, eid)


async def do_delete_episode(update: Update, ctx, eid: int) -> None:
    from modules.course_engine import delete_episode
    delete_episode(_db(ctx), eid)
    await update.callback_query.answer("حذف شد.")
    await show_episodes(update, ctx)


async def do_toggle_offer(update: Update, ctx, oid: int) -> None:
    db = _db(ctx)
    r = db.fetchone("SELECT is_active FROM offers WHERE id=?", (oid,))
    if r:
        db.execute("UPDATE offers SET is_active=? WHERE id=?", (0 if r["is_active"] else 1, oid))
    await update.callback_query.answer(A.TOGGLED)
    await show_offers(update, ctx)


# ---------- callback router ----------

@admin_required
async def on_admin_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    data = q.data or ""
    if not validate_callback(data):
        await q.answer("درخواست نامعتبر.", show_alert=True)
        return
    action, arg = parse_callback(data)
    try:
        if action != "adm":
            return
        head, _, rest = arg.partition(":")
        if head == "menu":
            await _send_menu(update, ctx, edit=True)
        elif head == "stats":
            await show_stats(update, ctx)
        elif head == "users":
            await show_users(update, ctx)
        elif head == "usersearch":
            _set_adm(ctx, "usersearch", "q")
            await q.answer()
            await update.effective_message.reply_text(A.ASK_USER_QUERY)
        elif head == "user":
            await show_user_detail(update, ctx, int(rest))
        elif head == "stage":
            db = _db(ctx)
            c = _browse_course(db, ctx)
            cslug = c["slug"] if c else None
            users = filter_by_stage(db, rest, 3, cslug)[:15]
            total = len(filter_by_stage(db, rest, 3, cslug))
            lines = [f"{A.STAGE_NAMES.get(rest, rest)} ({total} نفر):"] + [user_line(u) for u in users]
            kb = [[InlineKeyboardButton(f"👤 {u.get('full_name') or u['telegram_id']}",
                                        callback_data=f"adm:user:{u['id']}")] for u in users]
            await q.answer()
            await _view(q, "\n".join(lines)[:4000], reply_markup=_back_kb(kb))
        elif head == "eps":
            await show_episodes(update, ctx)
        elif head == "ep":
            await show_episode_detail(update, ctx, int(rest))
        elif head == "epdel":
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("🗑 بله، حذف کن", callback_data=f"adm:epdelok:{rest}")],
                [InlineKeyboardButton("انصراف", callback_data=f"adm:ep:{rest}")]])
            await q.answer()
            await _view(q, "این اپیزود برای همیشه حذف شود؟ پیشرفت کاربران در آن هم پاک می‌شود.",
                                      reply_markup=kb)
        elif head == "epdelok":
            await do_delete_episode(update, ctx, int(rest))
        elif head == "eptitle":
            _set_adm(ctx, "epedit", "value", {"ep_id": int(rest), "field": "title", "max": 200})
            await q.answer()
            await update.effective_message.reply_text("عنوان جدید اپیزود را بفرست:")
        elif head == "eptext":
            _set_adm(ctx, "epedit", "value", {"ep_id": int(rest), "field": "caption", "max": 4000})
            await q.answer()
            await update.effective_message.reply_text("متن جدید اپیزود را بفرست:")
        elif head == "eptoggle":
            await do_toggle_episode(update, ctx, int(rest))
        elif head == "epmove":
            eid_s, _, d_s = rest.partition(":")
            await do_move_episode(update, ctx, int(eid_s), int(d_s))
        elif head == "epadd":
            _set_adm(ctx, "epadd", "title", {})
            await q.answer()
            await update.effective_message.reply_text(A.ASK_EP_TITLE)
        elif head == "bulk":
            _set_adm(ctx, "bulkep", "text", {})
            await q.answer()
            await update.effective_message.reply_text(BULK_HELP)
        elif head == "bulkok":
            await do_bulk_save(update, ctx)
        elif head == "p":
            eid_s, _, no_s = rest.partition(":")
            await show_episode_detail(update, ctx, int(eid_s))
        elif head == "media":
            _set_adm(ctx, "mediaadd", "media", {"ep_id": int(rest)})
            await q.answer()
            await update.effective_message.reply_text(A.ASK_MEDIA)
        elif head == "mediadel":
            from modules.course_engine import set_episode_media
            set_episode_media(_db(ctx), int(rest), None, None)
            await q.answer("رسانه حذف شد.")
            await show_episode_detail(update, ctx, int(rest))
        elif head == "offers":
            await show_offers(update, ctx)
        elif head == "offtoggle":
            await do_toggle_offer(update, ctx, int(rest))
        elif head == "offadd":
            _set_adm(ctx, "offadd", "slug", {})
            await q.answer()
            await update.effective_message.reply_text(A.ASK_OFFER_SLUG)
        elif head == "offscope":
            st = _adm_state(ctx)
            if not st or st.get("flow") != "offadd":
                await q.answer()
                return
            db = _db(ctx)
            d = st["data"]
            cid = None
            if rest == "course":
                c = _browse_course(db, ctx)
                cid = c["id"] if c else None
            upsert_offer(db, d["slug"], d["title"], d["text"], d["url"],
                         d["button"], d["trigger"], course_id=cid)
            _clear_adm(ctx)
            await q.answer(A.SAVED)
            await update.effective_message.reply_text(f"{A.SAVED} ({d['slug']})")
            await _saved_nav(update.effective_message, [
                [InlineKeyboardButton("🎁 لیست پیشنهادها", callback_data="adm:offers")]])
        elif head == "offdel":
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("🗑 بله، حذف کن", callback_data=f"adm:offdelok:{rest}")],
                [InlineKeyboardButton("انصراف", callback_data="adm:offers")]])
            await q.answer()
            await _view(q, "این پیشنهاد و آمارش حذف شود؟", reply_markup=kb)
        elif head == "offdelok":
            await do_delete_offer(update, ctx, int(rest))
        elif head == "msg":
            await show_msg(update, ctx)
        elif head == "msgaud":
            await ask_audience(update, ctx)
        elif head == "msgaudset":
            await set_audience(update, ctx, rest)
        elif head == "msgstage":
            st = _adm_state(ctx)
            if not st or st.get("flow") != "msg":
                await q.answer()
                return
            st["data"]["stage"] = rest
            if rest == "inactive":
                st["step"] = "days"
                await q.answer()
                await update.effective_message.reply_text(A.ASK_MSG_DAYS)
            else:
                st["data"]["days"] = 3
                await show_msg_confirm(update, ctx, st)
        elif head == "msgconfirm":
            await do_queue_message(update, ctx)
        elif head == "courses":
            await show_courses(update, ctx)
        elif head == "course":
            await show_course_detail(update, ctx, rest)
        elif head == "courseadd":
            _set_adm(ctx, "courseadd", "title", {})
            await q.answer()
            await update.effective_message.reply_text(A.ASK_COURSE_TITLE)
        elif head == "coursetoggle":
            await do_toggle_course(update, ctx, int(rest))
        elif head == "coursedel":
            c = _db(ctx).fetchone("SELECT title FROM courses WHERE id=?", (int(rest),))
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("🗑 بله، کل دوره حذف شود", callback_data=f"adm:coursedelok:{rest}")],
                [InlineKeyboardButton("انصراف", callback_data="adm:courses")]])
            await q.answer()
            await safe_edit(q,
                f"«{c['title'] if c else '?'}» با همه اپیزودها و پارت‌هایش حذف شود؟ پیشرفت کاربران در این دوره هم پاک می‌شود.",
                reply_markup=kb)
        elif head == "coursedelok":
            await do_delete_course(update, ctx, int(rest))
        elif head == "texts":
            await show_texts(update, ctx)
        elif head == "text":
            # adm:text:<key>[:<user-callback to return to>] - the tail is how an
            # admin editing copy from inside the user flow gets back to the screen
            # they were previewing.
            key, _, back = rest.partition(":")
            await ask_text_value(update, ctx, key, back)
        elif head == "textreset":
            await reset_text_view(update, ctx, rest)
        elif head == "textsof":
            page, _, back = rest.partition(":")
            await show_page_texts(update, ctx, page, back)

        elif head == "pays":
            await show_pays(update, ctx)
        elif head == "payok":
            await decide_pay(update, ctx, int(rest), True)
        elif head == "payno":
            await decide_pay(update, ctx, int(rest), False)
        elif head == "analytics":
            await show_analytics(update, ctx)
        elif head == "cancel":
            _clear_adm(ctx)
            await q.answer()
            await update.effective_message.reply_text(A.CANCELLED)
    except (ValueError, IndexError):
        try:
            await q.answer("ورودی نامعتبر.", show_alert=True)
        except Exception:
            pass
    except Exception:
        log.exception("admin callback failed")
        try:
            await q.answer("خطا. دوباره تلاش کن.", show_alert=True)
        except Exception:
            pass


# ---------- message wizards ----------

async def ask_audience(update: Update, ctx) -> None:
    q = update.callback_query
    st = _adm_state(ctx)
    if not st or st.get("flow") != "msg":
        # started from button without text: begin flow asking text first
        _set_adm(ctx, "msg", "text", {})
        await q.answer()
        await update.effective_message.reply_text(A.ASK_MSG_TEXT)
        return
    await q.answer()
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("یک نفر خاص", callback_data="adm:msgaudset:single"),
         InlineKeyboardButton("همه کاربران", callback_data="adm:msgaudset:all")],
        [InlineKeyboardButton("یک گروه (مرحله دوره)", callback_data="adm:msgaudset:stage")],
        [InlineKeyboardButton(A.BTN_CANCEL, callback_data="adm:cancel")],
    ])
    await update.effective_message.reply_text(A.MSG_AUDIENCE_Q, reply_markup=kb)


async def set_audience(update: Update, ctx, which: str) -> None:
    q = update.callback_query
    st = _adm_state(ctx)
    if not st or st.get("flow") != "msg":
        await q.answer()
        return
    await q.answer()
    if which == "single":
        st["step"] = "target"
        await update.effective_message.reply_text(A.ASK_MSG_SINGLE_ID)
    elif which == "all":
        st["data"].update(scope="all", stage="", days=0)
        await show_msg_confirm(update, ctx, st)
    else:
        st["step"] = "stage"
        kb = InlineKeyboardMarkup(
            [[InlineKeyboardButton(A.STAGE_NAMES[s], callback_data=f"adm:msgstage:{s}")] for s in STAGES]
            + [[InlineKeyboardButton(A.BTN_CANCEL, callback_data="adm:cancel")]])
        await update.effective_message.reply_text("کدام گروه؟", reply_markup=kb)


async def show_msg_confirm(update: Update, ctx, st: dict) -> None:
    db = _db(ctx)
    d = st["data"]
    scope = d.get("scope", "filtered")
    if scope == "single":
        count, desc = 1, f"یک نفر (ID {d.get('target')})"
    elif scope == "all":
        count = len(audience_ids(db, {}))
        desc = f"همه کاربران ({count} نفر)"
    else:
        count = len(audience_ids(db, {"stage": d.get("stage", ""), "inactive_days": d.get("days", 3)}))
        desc = f"گروه «{A.STAGE_NAMES.get(d.get('stage', ''), d.get('stage'))}» ({count} نفر)"
    st["step"] = "confirm"
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ تأیید و ارسال", callback_data="adm:msgconfirm")],
        [InlineKeyboardButton(A.BTN_CANCEL, callback_data="adm:cancel")],
    ])
    preview = (d.get("text", "") or "")[:300]
    await update.effective_message.reply_text(
        f"{A.MSG_CONFIRM}\n\nگیرنده: {desc}\n\nمتن:\n{preview}", reply_markup=kb)


async def do_queue_message(update: Update, ctx) -> None:
    db = _db(ctx)
    st = _adm_state(ctx)
    q = update.callback_query
    if not st or st.get("flow") != "msg":
        await q.answer()
        return
    d = st["data"]
    scope = d.get("scope", "filtered")
    if scope == "single":
        queue_message(db, d["text"], scope="single", target_user_id=int(d["target"]))
    elif scope == "all":
        queue_message(db, d["text"], scope="filtered", filter_json={})
    else:
        queue_message(db, d["text"], scope="filtered",
                      filter_json={"stage": d.get("stage", ""), "inactive_days": int(d.get("days", 3))})
    _clear_adm(ctx)
    await q.answer(A.MSG_QUEUED)
    await update.effective_message.reply_text(A.MSG_QUEUED)
    await _saved_nav(update.effective_message, [
        [InlineKeyboardButton("📣 پیام‌ها", callback_data="adm:msg")]])


async def admin_consume_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> bool:
    """Run one wizard step for admins. Returns True if the message was consumed."""
    if not is_admin_update(update, ctx):
        return False
    st = _adm_state(ctx)
    if not st:
        return False
    text = (update.effective_message.text or "").strip()
    if text == "/admin":
        return False
    flow, step, d = st["flow"], st["step"], st["data"]
    msg = update.effective_message
    try:
        if flow == "courseadd":
            db = _db(ctx)
            if step == "title":
                if len(text) < 2 or len(text) > 200:
                    await msg.reply_text("عنوان باید ۲ تا ۲۰۰ حرف باشد.")
                else:
                    d["title"] = text
                    st["step"] = "desc"
                    await msg.reply_text(A.ASK_COURSE_DESC)
            elif step == "desc":
                c = create_course(db, auto_slug(db), d["title"], "" if text == "-" else text[:2000])
                ctx.user_data["adm_course"] = c["slug"]
                _clear_adm(ctx)
                await msg.reply_text(f"{A.SAVED} (دوره «{c['title']}» — حالا دوره جاری مدیریت است)")
                await _saved_nav(msg, [
                    [InlineKeyboardButton("📺 ساخت اپیزود برای همین دوره", callback_data="adm:eps")]])
            return True
        if flow == "textedit" and step == "value":
            from bot.texts import set_text
            mx = int(d.get("max", 2000))
            if not text or len(text) > mx:
                await msg.reply_text(f"متن باید ۱ تا {mx} حرف باشد.")
            else:
                set_text(_db(ctx), d["key"], text)
                back = d.get("back") or ""
                _clear_adm(ctx)
                await msg.reply_text(f"{A.SAVED} (از این به بعد همین متن به کاربران نمایش داده می‌شود)")
                # the back button is a plain user callback, so the normal user
                # router repaints the screen the admin was previewing - with the
                # new wording already in it.
                rows = []
                if back:
                    rows.append([InlineKeyboardButton("🔙 بازگشت به صفحه", callback_data=back)])
                rows.append([InlineKeyboardButton("📝 لیست متن‌ها", callback_data="adm:texts")])
                await _saved_nav(msg, rows)
            return True

        if flow == "bulkep" and step == "text":
            eps, errs = parse_bulk(text)
            over = [e["no"] for e in eps
                    if len("\n\n".join([e["caption"], *e["parts"]]).strip()) > 4000]
            if over:
                errs.append(f"متن اپیزود {over[0]} بیش از ۴۰۰۰ حرف است؛ خلاصه‌اش کن.")
            if errs or not eps:
                await msg.reply_text("❌\n" + "\n".join(errs[:8]) + "\n\nدوباره با قالب درست بفرست.")
            else:
                st["data"]["parsed"] = eps
                st["step"] = "confirm"
                preview = "\n".join(f"Ep{e['no']}: {e['title']}" for e in eps[:12])
                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton(f"✅ بساز ({len(eps)} اپیزود)", callback_data="adm:bulkok")],
                    [InlineKeyboardButton(A.BTN_CANCEL, callback_data="adm:cancel")]])
                await msg.reply_text(f"پیش‌نمایش:\n{preview}\n{'…' if len(eps) > 12 else ''}", reply_markup=kb)
            return True
        if flow == "epedit" and step == "value":
            mx = int(d.get("max", 2000))
            if not text or len(text) > mx:
                await msg.reply_text(f"متن باید ۱ تا {mx} حرف باشد.")
            else:
                await _save_ep_field(update, ctx, int(d["ep_id"]), d["field"], text)
            return True
        if flow == "usersearch" and step == "q":
            db = _db(ctx)
            rows = search(db, text)[:12]
            _clear_adm(ctx)
            if not rows:
                await msg.reply_text("کسی پیدا نشد. /admin")
                return True
            kb = InlineKeyboardMarkup(
                [[InlineKeyboardButton(f"👤 {u.get('full_name') or u['telegram_id']}",
                                       callback_data=f"adm:user:{u['id']}")] for u in rows]
                + [[InlineKeyboardButton(A.BTN_BACK_MENU, callback_data="adm:menu")]])
            await msg.reply_text(f"{len(rows)} نتیجه اول:", reply_markup=kb)
            return True
        if flow == "epadd":
            from modules.course_engine import next_episode_no
            db = _db(ctx)
            c = _browse_course(db, ctx)
            if not c:
                _clear_adm(ctx)
                await msg.reply_text("اول یک دوره بساز. /admin")
                return True
            if step == "title":
                if len(text) < 2 or len(text) > 200:
                    await msg.reply_text("عنوان باید ۲ تا ۲۰۰ حرف باشد.")
                else:
                    d["title"] = text
                    st["step"] = "content"
                    await msg.reply_text(A.ASK_EP_CONTENT)
            elif step == "content":
                no = next_episode_no(db, c["slug"])
                upsert_episode(db, c["slug"], no, d["title"], text[:4000])
                ep = get_episode(db, c["slug"], no)
                _clear_adm(ctx)
                await msg.reply_text(f"{A.SAVED} (اپیزود {no} در «{c['title']}»)")
                await _saved_nav(msg, [
                    [InlineKeyboardButton("🧩 مشاهده اپیزود",
                                          callback_data=f"adm:ep:{ep['id']}")],
                    [InlineKeyboardButton("📺 لیست اپیزودها", callback_data="adm:eps")]])
            elif step == "desc":
                no = next_episode_no(db, c["slug"])
                upsert_episode(db, c["slug"], no, d["title"],
                               "" if text == "-" else text[:4000])
                ep = get_episode(db, c["slug"], no)
                if d.get("file_id"):
                    from modules.course_engine import set_episode_media
                    set_episode_media(db, ep["id"], d["kind"], d["file_id"])
                _clear_adm(ctx)
                await msg.reply_text(f"{A.SAVED} (اپیزود {no} در «{c['title']}»)")
                await _saved_nav(msg, [
                    [InlineKeyboardButton("🧩 مشاهده اپیزود",
                                          callback_data=f"adm:ep:{ep['id']}")],
                    [InlineKeyboardButton("📺 لیست اپیزودها", callback_data="adm:eps")]])
            return True
        if flow == "offadd":
            db = _db(ctx)
            if step == "slug":
                d["slug"] = v_slug(text)
                st["step"] = "title"
                await msg.reply_text(A.ASK_OFFER_TITLE)
            elif step == "title":
                d["title"] = text[:200]
                st["step"] = "text"
                await msg.reply_text(A.ASK_OFFER_TEXT)
            elif step == "text":
                d["text"] = text[:4000]
                st["step"] = "button"
                await msg.reply_text(A.ASK_OFFER_BUTTON)
            elif step == "button":
                d["button"] = text[:64]
                st["step"] = "url"
                await msg.reply_text(A.ASK_OFFER_URL)
            elif step == "url":
                d["url"] = v_url(text)
                st["step"] = "trigger"
                await msg.reply_text(A.ASK_OFFER_TRIGGER)
            elif step == "trigger":
                d["trigger"] = v_trigger(text)
                st["step"] = "scope"
                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton("همین دوره", callback_data="adm:offscope:course"),
                     InlineKeyboardButton("🌍 همه دوره‌ها", callback_data="adm:offscope:global")],
                    [InlineKeyboardButton(A.BTN_CANCEL, callback_data="adm:cancel")]])
                await msg.reply_text("این پیشنهاد مخصوص کدام دوره باشد؟", reply_markup=kb)
            return True
        if flow == "msg":
            if step == "text":
                if len(text) < 1 or len(text) > 4000:
                    await msg.reply_text("متن باید ۱ تا ۴۰۰۰ حرف باشد.")
                else:
                    d["text"] = text
                    d["scope"] = "filtered"
                    st["step"] = "audience"
                    kb = InlineKeyboardMarkup([
                        [InlineKeyboardButton("یک نفر خاص", callback_data="adm:msgaudset:single"),
                         InlineKeyboardButton("همه کاربران", callback_data="adm:msgaudset:all")],
                        [InlineKeyboardButton("یک گروه (مرحله دوره)", callback_data="adm:msgaudset:stage")],
                        [InlineKeyboardButton(A.BTN_CANCEL, callback_data="adm:cancel")],
                    ])
                    await msg.reply_text(A.MSG_AUDIENCE_Q, reply_markup=kb)
            elif step == "target":
                d["target"] = int(text)
                d["scope"] = "single"
                await show_msg_confirm(update, ctx, st)
            elif step == "days":
                days = int(text)
                if not 0 <= days <= 365:
                    raise ValueError("range")
                d["days"] = days
                await show_msg_confirm(update, ctx, st)
            return True
    except (ValueError, KeyError):
        hints = {"no": A.INVALID_NUMBER, "target": A.INVALID_NUMBER, "days": A.INVALID_NUMBER,
                 "slug": A.INVALID_SLUG, "url": A.INVALID_URL, "trigger": A.INVALID_TRIGGER}
        await msg.reply_text(hints.get(step, "ورودی نامعتبر؛ دوباره بفرست."))
        return True
    except Exception:
        log.exception("admin wizard failed")
        await msg.reply_text("خطا. /admin")
        return True
    return False


async def admin_consume_media(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> bool:
    """Capture media into epadd/mediaadd wizards (kind auto-detected).
    Stray media from the admin gets a hint (never silence)."""
    if not is_admin_update(update, ctx):
        return False
    m = update.effective_message
    file_id = None
    media_kind = None
    try:
        if m.photo:
            file_id, media_kind = m.photo[-1].file_id, "photo"
        elif getattr(m, "video", None):
            file_id, media_kind = m.video.file_id, "video"
        elif getattr(m, "voice", None):
            file_id, media_kind = m.voice.file_id, "voice"
        elif getattr(m, "video_note", None):
            file_id, media_kind = m.video_note.file_id, "video_note"
        elif getattr(m, "audio", None):
            file_id, media_kind = m.audio.file_id, "audio"
        elif getattr(m, "document", None):
            file_id, media_kind = m.document.file_id, "file"
    except Exception:
        log.warning("media extract failed")
    if not file_id:
        return False
    st = _adm_state(ctx)
    if not st or st.get("flow") not in ("mediaadd", "epadd"):
        await m.reply_text("فایل رسید 👍 ولی الان وسط ساخت محتوا نیستی. از /admin ← دوره ← «📺 اپیزودها» شروع کن.")
        return True
    if st["flow"] == "epadd":
        if st.get("step") != "content":
            await m.reply_text("الان متن توضیح را می‌خواهم، نه فایل. متنش را بفرست (یا «-» برای بدون متن).")
            return True
        st["data"]["kind"] = media_kind
        st["data"]["file_id"] = file_id
        st["step"] = "desc"
        await m.reply_text(f"فایل {KIND_FA.get(media_kind, media_kind)} دریافت شد ✅\n{A.ASK_EP_DESC}")
        return True
    # mediaadd: set episode media immediately
    from modules.course_engine import set_episode_media
    set_episode_media(_db(ctx), int(st["data"]["ep_id"]), media_kind, file_id)
    _clear_adm(ctx)
    await m.reply_text(f"{A.SAVED} (رسانه: {KIND_FA.get(media_kind, media_kind)})")
    await _saved_nav(m, [[InlineKeyboardButton("🧩 مشاهده اپیزود",
                                               callback_data=f"adm:ep:{st['data']['ep_id']}")]])
    return True


# ---------- bulk import (structured text -> episodes+parts) ----------

BULK_HELP = ("📥 ساخت گروهی\n\nیک پیام با این قالب بفرست — هر بلوک یک اپیزود می‌شود:\n\n"
             "۱. عنوان اپیزود اول\nمتن اپیزود (هر خط یک پاراگراف)\nادامه متن\n\n"
             "۲. عنوان اپیزود دوم\nمتنش\n\n"
             "قواعد: خط خالی = اپیزود بعدی؛ شماره اول خط اختیاری است؛ حداکثر ۵۰ اپیزود؛ "
             "متن هر اپیزود حداکثر ۴۰۰۰ حرف (خودکار چند پیام می‌شود).")


def parse_bulk(text: str, start_no: int = 1) -> tuple[list[dict], list[str]]:
    """Parse bulk text. Returns (episodes, errors). Pure function (unit-tested).
    episodes: [{no, title, caption, parts:[str]}]."""
    import re as _re
    episodes: list[dict] = []
    errors: list[str] = []
    cur: dict | None = None
    auto = start_no
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            cur = None
            continue
        m = _re.match(r"^(\d{1,3})\s*[.\)\:\-]\s*(.+)$", line)
        if m and (cur is None):
            no = int(m.group(1))
            if not 1 <= no <= 500:
                errors.append(f"شماره اپیزود نامعتبر (خط: {line[:40]})")
                cur = None
                continue
            rest = m.group(2).strip()
            title, _, caption = rest.partition("|")
            title, caption = title.strip(), caption.strip()[:4000]
            if not (2 <= len(title) <= 200):
                errors.append(f"عنوان نامعتبر (خط: {line[:40]})")
                cur = None
                continue
            if any(e["no"] == no for e in episodes):
                cur = next(e for e in episodes if e["no"] == no)
            else:
                cur = {"no": no, "title": title, "caption": caption, "parts": []}
                episodes.append(cur)
        elif cur is None:
            # first line without number: auto-numbered episode title
            title, _, caption = line.partition("|")
            title, caption = title.strip(), caption.strip()[:4000]
            if not (2 <= len(title) <= 200):
                errors.append(f"عنوان نامعتبر (خط: {line[:40]})")
                continue
            while any(e["no"] == auto for e in episodes):
                auto += 1
            cur = {"no": auto, "title": title, "caption": caption, "parts": []}
            episodes.append(cur)
            auto += 1
        else:
            if len(line) > 4000:
                errors.append(f"پاراگراف خیلی طولانی (اپیزود {cur['no']})")
            elif len(cur["parts"]) >= 30:
                errors.append(f"بیش از ۳۰ پاراگراف در اپیزود {cur['no']}")
            else:
                cur["parts"].append(line)
    episodes = [e for e in episodes if e["parts"]]
    if len(episodes) > 50:
        errors.append("بیش از ۵۰ اپیزود در یک پیام")
    if not episodes and not errors:
        errors.append("چیزی فهمیده نشد؛ قالب را چک کن.")
    return episodes, errors


async def do_bulk_save(update: Update, ctx) -> None:
    db = _db(ctx)
    st = _adm_state(ctx)
    q = update.callback_query
    if not st or st.get("flow") != "bulkep":
        await q.answer()
        return
    c = _browse_course(db, ctx)
    if not c:
        await q.answer("اول یک دوره بساز.", show_alert=True)
        return
    n_ep = 0
    for e in st["data"]["parsed"]:
        body = "\n\n".join([e["caption"], *[p for p in e["parts"] if p]]).strip()
        upsert_episode(db, c["slug"], e["no"], e["title"], body[:4000])
        n_ep += 1
    _clear_adm(ctx)
    await q.answer("ساخته شد ✅")
    await update.effective_message.reply_text(f"✅ {n_ep} اپیزود در «{c['title']}» ساخته شد.")
    await _saved_nav(update.effective_message, [
        [InlineKeyboardButton("📺 لیست اپیزودها", callback_data="adm:eps")]])

# ---------- courses ----------

async def show_courses(update: Update, ctx) -> None:
    db = _db(ctx)
    q = update.callback_query
    await q.answer()
    courses = list_courses(db, only_active=False)
    browsing = ctx.user_data.get("adm_course")
    rows = []
    for c in courses:
        st = course_stats(db, c["id"])
        cur = " 📍" if c["slug"] == browsing else ""
        rows.append([InlineKeyboardButton(
            f"{'✅' if c['is_active'] else '⏸'} {c['title']} ({st['episodes']} اپیزود، {st['starters']} شروع){cur}",
            callback_data=f"adm:course:{c['slug']}")])
    rows.append([InlineKeyboardButton("➕ دوره جدید", callback_data="adm:courseadd")])
    await _view(q, "📚 دوره‌ها\nروی هر دوره بزن تا مدیریت شود. 📍 یعنی دوره‌ای که الان داری مدیریتش می‌کنی.",
                              reply_markup=_back_kb(rows))


async def show_course_detail(update: Update, ctx, slug: str) -> None:
    db = _db(ctx)
    q = update.callback_query
    c = get_course(db, slug)
    if not c:
        await q.answer("دوره پیدا نشد.", show_alert=True)
        return
    await q.answer()
    ctx.user_data["adm_course"] = slug  # this is now the browsing course
    st = course_stats(db, c["id"])
    rows = [
        [InlineKeyboardButton("📺 اپیزودهای این دوره", callback_data="adm:eps")],
        [InlineKeyboardButton("غیرفعال کن" if c["is_active"] else "فعال کن",
                              callback_data=f"adm:coursetoggle:{c['id']}")],
        [InlineKeyboardButton("🗑 حذف دوره", callback_data=f"adm:coursedel:{c['id']}")],
        [InlineKeyboardButton("📚 لیست دوره‌ها", callback_data="adm:courses")],
    ]
    await _view(q, f"📚 {c['title']}\n{st['episodes']} اپیزود | {st['starters']} شروع‌کننده\n\n{c.get('description') or ''}",
                              reply_markup=_back_kb(rows))


async def do_toggle_course(update: Update, ctx, cid: int) -> None:
    db = _db(ctx)
    r = db.fetchone("SELECT is_active, slug FROM courses WHERE id=?", (cid,))
    if r:
        set_course_active(db, cid, not r["is_active"])
        await update.callback_query.answer(A.TOGGLED)
        await show_course_detail(update, ctx, r["slug"])
    else:
        await update.callback_query.answer("دوره پیدا نشد.", show_alert=True)


async def do_delete_course(update: Update, ctx, cid: int) -> None:
    db = _db(ctx)
    res = delete_course(db, cid)
    if ctx.user_data.get("adm_course"):
        c = db.fetchone("SELECT id FROM courses WHERE slug=?", (ctx.user_data["adm_course"],))
        if not c:
            ctx.user_data.pop("adm_course", None)
    await update.callback_query.answer("حذف شد.")
    await show_courses(update, ctx)


# ---------- texts ----------

async def show_texts(update: Update, ctx) -> None:
    """Every user-visible string in one place. The ✱ mark means "this one has been
    reworded from the shipped default" - without it an admin cannot tell their own
    copy from the original."""
    from bot.texts import TEXT_DEFS, is_overridden
    db = _db(ctx)
    q = update.callback_query
    await q.answer()
    rows = [[InlineKeyboardButton(f"✏️ {label}{' ✱' if is_overridden(db, key) else ''}",
                                  callback_data=f"adm:text:{key}")]
            for key, label, _ in TEXT_DEFS]
    await _view(q, "📝 متن‌های ربات\nکدام متن عوض شود؟ (✱ یعنی از پیش‌فرض تغییر کرده)\n"
                   "مقدار فعلی در مرحله بعد نشان داده می‌شود.",
                reply_markup=_back_kb(rows))


async def reset_text_view(update: Update, ctx, key: str) -> None:
    """Drop the override and fall back to the shipped default. A white-label edit
    with no undo is a one-way door."""
    from bot.texts import TEXT_DEFS, is_overridden, reset_text, t
    db = _db(ctx)
    meta = next((m for m in TEXT_DEFS if m[0] == key), None)
    if not meta:
        await update.callback_query.answer("متن پیدا نشد.", show_alert=True)
        return
    if not is_overridden(db, key):
        await update.callback_query.answer("این متن از قبل پیش‌فرض است.", show_alert=True)
        return
    reset_text(db, key)
    await update.callback_query.answer("↩️ به پیش‌فرض برگشت.", show_alert=True)
    await update.effective_message.reply_text(
        f"↩️ «{meta[1]}» به پیش‌فرض برگشت ✅\n\n{t(db, key)}",
        reply_markup=_back_kb([[InlineKeyboardButton("📝 لیست متن‌ها", callback_data="adm:texts")]]))


async def show_page_texts(update: Update, ctx, page: str, back: str) -> None:
    """The texts visible on one user-facing screen, for an admin standing on it.

    One button per screen rather than one per string: the menu alone carries four
    editable words, and four extra buttons on the menu is how a screen stops
    looking like a menu. The chooser is also the natural home for "reset to
    default", which would otherwise sit on every prompt.
    """
    from bot.handlers import PAGE_EDIT_KEYS
    from bot.texts import TEXT_DEFS, is_overridden
    db = _db(ctx)
    q = update.callback_query
    keys = PAGE_EDIT_KEYS.get(page)
    if not keys:
        await q.answer("این صفحه متن قابل‌ویرایشی ندارد.", show_alert=True)
        return
    defs = {k: label for k, label, _ in TEXT_DEFS}
    rows = [[InlineKeyboardButton(f"✏️ {defs[k]}{' ✱' if is_overridden(db, k) else ''}",
                                  callback_data=f"adm:text:{k}:{back}")]
            for k in keys if k in defs]
    if not rows:
        await q.answer("متنی برای این صفحه تعریف نشده.", show_alert=True)
        return
    if back:
        rows.append([InlineKeyboardButton("🔙 بازگشت به صفحه", callback_data=back)])
    await q.answer()
    await _view(q, "✏️ متن‌های این صفحه\n(✱ یعنی از پیش‌فرض تغییر کرده)\n\n"
                   "هر متنی را می‌بینی و همان را عوض می‌کنی — بدون نیاز به رفتن به پنل.",
                reply_markup=InlineKeyboardMarkup(rows))


async def ask_text_value(update: Update, ctx, key: str, back: str = "") -> None:
    from bot.texts import TEXT_DEFS, is_overridden, t
    db = _db(ctx)
    q = update.callback_query
    meta = next((m for m in TEXT_DEFS if m[0] == key), None)
    if not meta:
        await q.answer("متن پیدا نشد.", show_alert=True)
        return
    if _adm_state(ctx):
        # ctx.user_data["adm"] holds one flow. Tapping an edit button mid-wizard
        # would silently destroy whatever the admin was in the middle of.
        await q.answer("یک کار ناتمام داری. اول با «❌ انصراف» آن را ببند.", show_alert=True)
        return
    _set_adm(ctx, "textedit", "value", {"key": key, "max": meta[2], "back": back})
    rows = []
    if is_overridden(db, key):
        rows.append([InlineKeyboardButton("↩️ بازگشت به پیش‌فرض", callback_data=f"adm:textreset:{key}")])
    if back:
        rows.append([InlineKeyboardButton("🔙 بازگشت", callback_data=back)])
    kb = InlineKeyboardMarkup(rows) if rows else None
    await q.answer()
    await update.effective_message.reply_text(
        f"✏️ {meta[1]}\n\nمقدار فعلی:\n{t(db, key)}\n\nمقدار جدید را بفرست (حداکثر {meta[2]} حرف):",
        reply_markup=kb)



# ---------- purchases ----------

async def show_pays(update: Update, ctx) -> None:
    db = _db(ctx)
    q = update.callback_query
    await q.answer()
    pend = pending_purchases(db)
    lines = [f"⏳ در انتظار تأیید ({len(pend)}):"]
    kb_rows = []
    for p in pend:
        lines.append(f"#{p['id']} {p.get('full_name') or p['telegram_id']} {p.get('phone') or ''} — {p.get('offer_title') or '—'}")
        kb_rows.append([InlineKeyboardButton(f"✅ تأیید #{p['id']}", callback_data=f"adm:payok:{p['id']}"),
                        InlineKeyboardButton("❌ رد", callback_data=f"adm:payno:{p['id']}")])
    hist = purchase_history(db, 8)
    hlines = [f"{'✅' if h['status'] == 'completed' else '❌'} #{h['id']} {h.get('full_name') or h['telegram_id']}" for h in hist]
    txt = "\n".join(lines) + ("\n\nتاریخچه:\n" + "\n".join(hlines) if hlines else "\n\nتاریخچه‌ای نیست.")
    await _view(q, f"💰 خریدها\nمنتظرها را تأیید یا رد کن؛ تاریخچه پایین است.\n\n{txt}", reply_markup=_back_kb(kb_rows))


async def decide_pay(update: Update, ctx, pid: int, ok: bool) -> None:
    db = _db(ctx)
    p = approve_purchase(db, pid) if ok else decline_purchase(db, pid)
    q = update.callback_query
    if not p:
        await q.answer("این درخواست قبلاً بررسی شده.", show_alert=True)
        return
    await q.answer("✅ تأیید و ثبت شد." if ok else "رد شد.")
    try:
        u = db.fetchone("SELECT telegram_id FROM users WHERE id=?", (p["user_id"],))
        if u:
            await ctx.bot.send_message(
                chat_id=int(u["telegram_id"]),
                text="🎉 خریدت تأیید شد! به جمع اعضای ویژه خوش اومدی." if ok else
                     "درخواست خریدت تأیید نشد. برای هماهنگی پیام بده.")
    except Exception:
        log.warning("buyer notify failed for purchase %s", pid)
    await show_pays(update, ctx)
