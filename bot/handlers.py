"""Course-catalog bot wiring: thin layer over reusable modules.

Every user-facing string comes from bot.texts.t() (settings-overridable).
Every flow is per-course: the user's current course drives menu/episodes/offers.
"""
from __future__ import annotations
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from modules.buttons import back_only_kb, episode_list_kb, phone_request_kb, progress_bar, remove_kb
from modules.course_engine import (get_course, get_course_by_id, list_courses, list_episodes,
                                    get_episode)
from modules.offers import get_active_offer, log_interaction, request_purchase, should_show_offer
from modules.phone_verification import is_contact_message, validate_and_save
from modules.progress import can_access_episode, progress_summary
from modules.screens import render
from modules.telegram_core import is_admin, parse_callback, safe_edit_markup, validate_callback
from modules.users import get_or_create, set_name, touch, get_by_telegram
from modules.logging_mod import get_logger, user_error
import bot.texts as texts
from bot.texts import t

log = get_logger("bot")

# Which texts are visible on which screen, so an admin standing on that screen can
# reword exactly what he is looking at. The chooser in the admin panel reads this
# map, which also keeps the two sides from drifting apart.
PAGE_EDIT_KEYS = {
    "catalog": ("catalog_title", "catalog_empty"),
    "menu": ("catalog_progress", "unit_episode", "btn_courses", "offer_again"),
    "offer": ("paid_button", "btn_home"),
    "finished": ("course_finished", "btn_home", "catalog_progress"),
    "episode": ("catalog_progress", "btn_next_episode", "btn_home", "btn_courses"),
}


def _texts_row(ctx, user_id: int, page: str, back: str) -> list[list]:
    """One admin-only button that opens the editable texts of the current screen.

    Hidden for ordinary users (they would only be confused by it) - but hiding is
    convenience, not security: on_admin_callback re-checks ADMIN_IDS regardless.
    """
    if page not in PAGE_EDIT_KEYS or not is_admin(user_id, _cfg(ctx).admin_ids):
        return []
    return [[InlineKeyboardButton("✏️ متن‌های این صفحه",
                                  callback_data=f"adm:textsof:{page}:{back}")]]


def _with_texts_row(ctx, user_id: int, kb, page: str, back: str):
    """Append the admin row above the nav footer, leaving user keyboards untouched.
    kb may be None (a screen with no buttons of its own) for a non-admin."""
    extra = _texts_row(ctx, user_id, page, back)
    if not extra:
        return kb
    rows = [list(r) for r in kb.inline_keyboard] if kb is not None else []
    return InlineKeyboardMarkup(extra + rows)


def _db(ctx: ContextTypes.DEFAULT_TYPE):
    return ctx.application.bot_data["db"]


def _cfg(ctx):
    return ctx.application.bot_data["cfg"]


def _fresh(db, user: dict) -> dict:
    r = db.fetchone("SELECT * FROM users WHERE id=?", (user["id"],))
    return dict(r) if r else user


def _user_course(db, user: dict) -> dict | None:
    """The user's currently selected active course, or None."""
    user = _fresh(db, user)
    cid = user.get("current_course_id")
    if not cid:
        return None
    c = get_course_by_id(db, int(cid))
    return c if c and c["is_active"] else None


# ---------- offers (per course) ----------

def _offer_eligible(db, user_id: int, course_slug: str, course_id: int) -> dict | None:
    offer = get_active_offer(db, course_id)
    if offer and should_show_offer(db, user_id, course_slug, offer["trigger_rule"]):
        return offer
    return None


def _offer_block(db, offer: dict) -> tuple[list, str]:
    """An offer as (extra keyboard rows, extra body text), so any screen can carry
    one. The trailing home button is not optional: an offer without a way out is a
    dead end."""
    rows = [[InlineKeyboardButton(offer["button_text"], callback_data=f"offer:{offer['slug']}")],
            [InlineKeyboardButton(t(db, "paid_button"), callback_data=f"pay:{offer['slug']}")],
            [InlineKeyboardButton(t(db, "btn_home"), callback_data="menu:main")]]
    return rows, f"{offer['title']}\n\n{offer['text']}"


async def _send_offer(update: Update, ctx, user: dict, offer: dict) -> None:
    log_interaction(_db(ctx), user["id"], offer["id"], "viewed")
    db = _db(ctx)
    rows, body = _offer_block(db, offer)
    if update.callback_query:
        try:
            await update.callback_query.answer()
        except Exception:
            pass
    kb = _with_texts_row(ctx, user["id"], InlineKeyboardMarkup(rows), "offer", "offer:menu")
    await render(update, ctx, body, kb)


async def _notify_admins(ctx, text: str, kb=None) -> None:
    for aid in _cfg(ctx).admin_ids:
        try:
            await ctx.bot.send_message(chat_id=int(aid), text=text, reply_markup=kb)
        except Exception:
            log.warning("admin notify failed for %s", aid)


LINK_TTL_SECONDS = 30


async def _expire_link(job_ctx) -> None:
    """Job callback: take the link message back down. Silence is the point - by
    the time this runs the user has long since tapped or ignored it.

    PTB hands the callback a CallbackContext, not a Job: the bot is on the
    context, the ids on context.job.
    """
    try:
        await job_ctx.bot.delete_message(chat_id=job_ctx.job.chat_id,
                                         message_id=job_ctx.job.data)
    except Exception:
        pass


async def _send_link(update: Update, ctx, text: str) -> None:
    """Post a link, then remove it. A purchase URL left in the chat is permanent
    clutter that nothing in the flow needs, so it gets a TTL instead of a shelf."""
    msg = await update.effective_message.reply_text(text)
    mid = getattr(msg, "message_id", None)
    if mid is None:
        return
    try:
        jq = ctx.job_queue
    except Exception:
        return  # no job queue (tests, custom bootstrap): the link just stays
    if jq is None:
        return
    try:
        jq.run_once(_expire_link, LINK_TTL_SECONDS, data=mid, chat_id=update.effective_chat.id)
    except Exception:
        log.debug("link expiry not scheduled")


async def _on_paid(update: Update, ctx, user: dict, course: dict, slug: str) -> None:
    from bot.admin_handlers import user_line  # local: admin presentation lives there
    db = _db(ctx)
    offer = db.fetchone("SELECT * FROM offers WHERE slug=?", (slug,))
    if not offer:
        await update.callback_query.answer("پیشنهاد فعال نیست.")
        return
    req = request_purchase(db, user["id"], int(offer["id"]))
    await update.callback_query.answer()
    await update.effective_message.reply_text(t(db, "paid_received"))
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ تأیید خرید", callback_data=f"adm:payok:{req['id']}"),
         InlineKeyboardButton("❌ رد", callback_data=f"adm:payno:{req['id']}")]])
    await _notify_admins(
        ctx, f"💰 درخواست خرید #{req['id']}\n{user_line(user)}\nدوره: {course['title']}\nپیشنهاد: {offer['title']}", kb)


# ---------- catalog ----------

async def show_catalog(update: Update, ctx, user: dict) -> None:
    db = _db(ctx)
    courses = list_courses(db, only_active=True)
    if not courses:
        if update.callback_query:
            await update.callback_query.answer()
        await render(update, ctx, t(db, "catalog_empty"),
                     _with_texts_row(ctx, user["id"], None, "catalog", "menu:catalog"))
        return
    rows = []
    for c in courses:
        s = progress_summary(db, user["id"], c["slug"])
        mark = "✅ " if s["finished"] else ("▶️ " if s["done"] else "")
        rows.append([InlineKeyboardButton(
            f"{mark}{c['title']} ({s['done']}/{s['total']})", callback_data=f"course:{c['slug']}")])
    kb = _with_texts_row(ctx, user["id"], InlineKeyboardMarkup(rows), "catalog", "menu:catalog")
    if update.callback_query:
        await update.callback_query.answer()
    await render(update, ctx, t(db, "catalog_title"), kb)


async def select_course(update: Update, ctx, user: dict, slug: str) -> None:
    db = _db(ctx)
    c = get_course(db, slug)
    if not c or not c["is_active"]:
        if update.callback_query:
            await update.callback_query.answer("این دوره فعال نیست.", show_alert=True)
        return
    db.execute("UPDATE users SET current_course_id=? WHERE id=?", (c["id"], user["id"]))
    touch(db, user["id"])
    await show_menu(update, ctx, _fresh(db, user))


# ---------- course views ----------

async def show_menu(update: Update, ctx, user: dict) -> None:
    db = _db(ctx)
    course = _user_course(db, user)
    if not course:
        await show_catalog(update, ctx, user)
        return
    s = progress_summary(db, user["id"], course["slug"])
    eps = list_episodes(db, course["slug"])
    bar = progress_bar(s["done"], s["total"])
    head = texts.render(db, "catalog_progress", done=s["done"], total=s["total"])
    # The menu stays the menu even when the course is done. Swapping the title for
    # the congratulations made every "🏠 منو" tap read like another celebration,
    # and hid which course the menu belonged to.
    txt = f"{course['title']}\n{head}\n{bar}"
    kb = episode_list_kb([{"episode_no": e["episode_no"], "title": e["title"]} for e in eps], s["unlocked"],
                         unit=t(db, "unit_episode"))
    if _offer_eligible(db, user["id"], course["slug"], course["id"]):
        rows = [list(r) for r in kb.inline_keyboard]
        rows.append([InlineKeyboardButton(t(db, "offer_again"), callback_data="offer:menu")])
        kb = InlineKeyboardMarkup(rows)
    rows = [list(r) for r in kb.inline_keyboard]
    rows.append([InlineKeyboardButton(t(db, "btn_courses"), callback_data="menu:catalog")])
    footer = _with_texts_row(ctx, user["id"], InlineKeyboardMarkup(rows), "menu", "menu:main")
    if update.callback_query:
        await update.callback_query.answer()
    await render(update, ctx, txt, footer)


def _ep_nav_kb(ctx, db, user_id: int, episode_no: int, has_next: bool):
    rows = []
    if has_next:
        rows.append([InlineKeyboardButton(
            texts.render(db, "btn_next_episode", next=episode_no + 1),
            callback_data=f"ep:{episode_no + 1}")])
    rows.append([InlineKeyboardButton(t(db, "btn_home"), callback_data="menu:main"),
                 InlineKeyboardButton(t(db, "btn_courses"), callback_data="menu:catalog")])
    kb = InlineKeyboardMarkup(rows)
    extra = _texts_row(ctx, user_id, "episode", "menu:main")
    return InlineKeyboardMarkup(extra + rows) if extra else kb


async def _deliver_episode(update: Update, ctx, ep: dict, kb, progress_line: str) -> None:
    """Episode = optional media + auto-chunked text. Nav buttons ALWAYS ride on
    the LAST message sent (media alone never strands the user)."""
    from modules.buttons import split_text
    bot, chat_id = ctx.bot, update.effective_chat.id
    q = update.callback_query
    if q:
        try:
            await q.answer()
        except Exception:
            pass
    title = f"📺 {ep['title']}"
    kind, fid = ep.get("cover_kind"), ep.get("cover_file_id")
    chunks = split_text(ep.get("caption") or "")

    def _sender():
        table = {"photo": ("send_photo", "photo"), "video": ("send_video", "video"),
                 "audio": ("send_audio", "audio"), "voice": ("send_voice", "voice"),
                 "file": ("send_document", "document")}
        if kind not in table:
            return None, None
        meth, arg = table[kind]
        return getattr(bot, meth, None), arg

    sender, arg = _sender()
    media_ok = False
    if fid and sender:
        try:
            cap = title if chunks else f"{title}\n\n{progress_line}"
            await sender(chat_id=chat_id, **{arg: fid}, caption=cap,
                         reply_markup=kb if not chunks else None)
            media_ok = True
        except Exception:
            log.warning("episode media failed")
            await bot.send_message(chat_id=chat_id, text=f"{title}\n(خطا در ارسال رسانه)")
    elif fid and kind == "video_note":
        try:
            await bot.send_video_note(chat_id=chat_id, video_note=fid)
            media_ok = True  # note sent; buttons go on a trailing message below
        except Exception:
            log.warning("episode video_note failed")
    for i, ch in enumerate(chunks):
        last = i == len(chunks) - 1
        head = title + "\n\n" if (i == 0 and not media_ok) else ""
        tail = f"\n\n{progress_line}" if last else ""
        await bot.send_message(chat_id=chat_id, text=f"{head}{ch}{tail}",
                               reply_markup=kb if last else None)
    if not chunks and (not fid or not media_ok or kind == "video_note"):
        await bot.send_message(chat_id=chat_id, text=f"{title}\n\n{progress_line}", reply_markup=kb)


async def show_episode(update: Update, ctx, user: dict, course: dict, episode_no: int) -> None:
    db = _db(ctx)
    if not can_access_episode(db, user["id"], course["slug"], episode_no):
        q = update.callback_query
        if q:
            await q.answer(t(db, "locked"), show_alert=True)
        elif update.effective_message:
            await update.effective_message.reply_text(t(db, "locked"))
        return
    ep = get_episode(db, course["slug"], episode_no)
    if not ep:
        # The button outlived its episode (deleted, or deactivated course). Say so
        # and take the dead row off the message, so nothing dangles.
        msg = t(db, "episode_gone")
        q = update.callback_query
        if q:
            await q.answer(msg, show_alert=True)
            await safe_edit_markup(q, back_only_kb("menu:main", t(db, "btn_home")))
        elif update.effective_message:
            await update.effective_message.reply_text(msg)
        return
    # open-counts-as-seen: entering completes the episode (idempotent).
    # Read the finish state *first*: complete_episode is idempotent, so without
    # this the course would congratulate the user again on every re-visit to the
    # last episode.
    was_finished = progress_summary(db, user["id"], course["slug"])["finished"]
    from modules.progress import complete_episode as _complete_ep
    try:
        _complete_ep(db, user["id"], course["slug"], episode_no)
    except PermissionError:
        q = update.callback_query
        if q:
            await q.answer(t(db, "locked"), show_alert=True)
        elif update.effective_message:
            await update.effective_message.reply_text(t(db, "locked"))
        return
    s = progress_summary(db, user["id"], course["slug"])
    bar = progress_bar(s["done"], s["total"])
    eps = list_episodes(db, course["slug"])
    has_next = any(int(e["episode_no"]) > episode_no for e in eps)
    await _deliver_episode(update, ctx, ep, _ep_nav_kb(ctx, db, user["id"], episode_no, has_next),
                           f"{texts.render(db, 'catalog_progress', done=s['done'], total=s['total'])}\n{bar}")
    if s["finished"] and not was_finished:
        await _course_finished(update, ctx, user, course, s, bar)


async def _course_finished(update: Update, ctx, user: dict, course: dict, s: dict, bar: str) -> None:
    """The celebration is a *view*, not an event: it lives on the screen. Pushing
    it meant every re-visit to the last episode stacked another 'تبریک' on the
    chat. When there is an offer to show it rides on the same screen, so the two
    cannot push each other out of existence."""
    db = _db(ctx)
    fresh = _fresh(db, user)
    offer = _offer_eligible(db, fresh["id"], course["slug"], course["id"])
    txt = (f"{t(db, 'course_finished')}\n\n"
           f"{texts.render(db, 'catalog_progress', done=s['done'], total=s['total'])}\n{bar}")
    if offer:
        log_interaction(db, fresh["id"], offer["id"], "viewed")
        rows, body = _offer_block(db, offer)
        txt = f"{txt}\n\n{body}"
    else:
        rows = [[InlineKeyboardButton(t(db, "btn_home"), callback_data="menu:main")]]
    kb = _with_texts_row(ctx, fresh["id"], InlineKeyboardMarkup(rows), "finished", "menu:main")
    q = update.callback_query
    if q:
        try:
            await q.answer()
        except Exception:
            pass
    await render(update, ctx, txt, kb)


# ---------- commands & messages ----------

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        u = update.effective_user
        db = _db(ctx)
        user = get_or_create(db, u.id, u.username)
        touch(db, user["id"])
        if not user.get("phone"):
            await update.effective_message.reply_text(t(db, "welcome"),
                                                      reply_markup=phone_request_kb(t(db, "phone_button")))
            ctx.user_data["awaiting"] = "phone"
        elif not user.get("full_name"):
            await update.effective_message.reply_text(t(db, "ask_name"), reply_markup=remove_kb())
            ctx.user_data["awaiting"] = "name"
        else:
            await show_catalog(update, ctx, _fresh(db, user))
    except Exception as e:
        log.exception("start failed")
        await update.effective_message.reply_text(user_error(t(_db(ctx), "generic_error"), log, e))


async def on_contact(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        msg = update.effective_message
        if not is_contact_message(msg):
            return
        db = _db(ctx)
        tg_user = update.effective_user
        user = get_or_create(db, tg_user.id, tg_user.username)
        ok, res = validate_and_save(db, user["id"], msg.contact.phone_number,
                                    msg.contact.user_id, tg_user.id)
        if not ok:
            await msg.reply_text(res, reply_markup=phone_request_kb(t(db, "phone_button")))
            return
        user = _fresh(db, user)
        if user.get("phone") and user.get("full_name"):
            ctx.user_data["awaiting"] = None
            await msg.reply_text("شماره‌ات تأیید و به‌روز شد ✅", reply_markup=remove_kb())
            await show_catalog(update, ctx, user)
            return
        ctx.user_data["awaiting"] = "name"
        await msg.reply_text(t(db, "ask_name"), reply_markup=remove_kb())
    except Exception as e:
        log.exception("contact failed")
        await update.effective_message.reply_text(user_error(t(_db(ctx), "generic_error"), log, e))


async def on_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        from bot.admin_handlers import admin_consume_text
        if await admin_consume_text(update, ctx):
            return
        import re
        msg = update.effective_message
        text = (msg.text or "").strip()
        if not text or text.startswith("/"):
            return
        db = _db(ctx)
        user = get_by_telegram(db, update.effective_user.id)
        if not user or not user.get("phone"):
            if re.fullmatch(r"[\d\s+\-()]+", text) and len(re.sub(r"\D", "", text)) >= 10:
                await msg.reply_text(t(db, "typed_phone_hint"),
                                     reply_markup=phone_request_kb(t(db, "phone_button")))
            else:
                await msg.reply_text(t(db, "need_phone"),
                                     reply_markup=phone_request_kb(t(db, "phone_button")))
            ctx.user_data["awaiting"] = "phone"
            return
        if ctx.user_data.get("awaiting") == "name" or not user.get("full_name"):
            if len(text) < 2 or len(text) > 120:
                await msg.reply_text("لطفاً نام معتبر بنویس ✍️ (۲ تا ۱۲۰ حرف)")
                return
            if re.fullmatch(r"[\d\s+\-()]+", text):
                await msg.reply_text(t(db, "name_digits"))
                return
            set_name(db, user["id"], text)
            ctx.user_data["awaiting"] = None
            await msg.reply_text(t(db, "name_saved"), reply_markup=remove_kb())
            await show_catalog(update, ctx, _fresh(db, user))
            return
        await msg.reply_text(t(db, "menu_nudge"))
        await show_catalog(update, ctx, user)
    except Exception as e:
        log.exception("text handling failed")
        await update.effective_message.reply_text(user_error(t(_db(ctx), "generic_error"), log, e))


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        db = _db(ctx)
        user = get_by_telegram(db, update.effective_user.id)
        if not user or not user.get("phone"):
            await update.effective_message.reply_text(t(db, "help_new"))
        elif not user.get("full_name"):
            await update.effective_message.reply_text(t(db, "ask_name"))
        else:
            await update.effective_message.reply_text(t(db, "help_main"))
            await show_catalog(update, ctx, user)
    except Exception as e:
        log.exception("help failed")
        await update.effective_message.reply_text(user_error(t(_db(ctx), "generic_error"), log, e))


async def cmd_episodes(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        db = _db(ctx)
        user = get_by_telegram(db, update.effective_user.id)
        if not user or not user.get("phone"):
            await update.effective_message.reply_text(t(db, "start_first"))
            return
        await show_catalog(update, ctx, user)
    except Exception as e:
        log.exception("episodes cmd failed")
        await update.effective_message.reply_text(user_error(t(_db(ctx), "generic_error"), log, e))


async def on_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    try:
        data = q.data or ""
        if data.startswith("adm:"):
            return  # owned by bot.admin_handlers
        if not validate_callback(data):
            await q.answer(t(_db(ctx), "invalid_callback"), show_alert=True)
            return
        action, arg = parse_callback(data)
        db = _db(ctx)
        user = get_by_telegram(db, update.effective_user.id)
        if not user or not user.get("phone"):
            await q.answer(t(db, "need_phone"), show_alert=True)
            return
        user = _fresh(db, user)
        if action == "menu":
            if arg == "catalog":
                await show_catalog(update, ctx, user)
            else:
                await show_menu(update, ctx, user)
            return
        if action == "course":
            await select_course(update, ctx, user, arg)
            return
        course = _user_course(db, user)
        if not course:
            await show_catalog(update, ctx, user)
            return
        if action == "ep":
            await show_episode(update, ctx, user, course, int(arg))
        elif action in ("part", "parts", "done"):
            # legacy buttons from pre-simplification messages: episode covers everything
            await show_episode(update, ctx, user, course, int(arg.partition(":")[0]))
        elif action == "locked":
            await q.answer(t(db, "locked"), show_alert=True)
        elif action == "offer":
            if arg == "menu":
                offer = _offer_eligible(db, user["id"], course["slug"], course["id"])
                if offer:
                    await _send_offer(update, ctx, user, offer)
                else:
                    await q.answer("پیشنهادی برایت فعال نیست.", show_alert=True)
                return
            offer = db.fetchone("SELECT * FROM offers WHERE slug=?", (arg,))
            if offer:
                log_interaction(db, user["id"], offer["id"], "clicked")
                await q.answer()
                await _send_link(update, ctx, f"{offer['button_text']}: {offer['url']}")
            else:
                await q.answer("پیشنهاد فعال نیست.")
        elif action == "pay":
            await _on_paid(update, ctx, user, course, arg)
        else:
            await q.answer(t(db, "invalid_callback"), show_alert=True)
    except Exception as e:
        log.exception("callback failed")
        try:
            await q.answer(t(_db(ctx), "generic_error"), show_alert=True)
        except Exception:
            pass
