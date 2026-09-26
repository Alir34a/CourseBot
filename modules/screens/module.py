"""One mutable menu message per chat, so browsing costs zero new messages.

Two message classes, with deliberately opposite rules:

  content  episode text and media. Never edited, never deleted - the user must be
           able to scroll back and re-read what they already worked through.
  screen   the single menu message the bot mutates in place (menu, catalog, offer).

Three navigation rules, picked so the bot never edits a message the user cannot see:

  nav button on the screen itself   edit in place          -> 0 new messages
  nav button on a content message   drop old screen, send  -> menu lands where you look
  command / plain text              drop old screen, send  -> fresh view on request

The middle rule is the whole point. Editing the tracked screen when the user just
tapped a button on an *episode* three messages up would change something off
screen: the spinner stops and nothing appears to happen. Deleting it and sending
the menu at the bottom puts the view exactly where the eyes already are.

The screen pointer lives in ctx.user_data, i.e. in memory. After a restart the bot
forgets it and leaves one stale screen behind rather than risking a wrong delete:
losing the pointer is harmless, acting on a stale one would not be.
"""
from __future__ import annotations
from telegram import Chat

from modules.logging_mod import get_logger
from modules.telegram_core import EDITED, FAILED, UNCHANGED, safe_edit

log = get_logger("screens")

SCREEN_KEY = "screen"
SENT = "sent"

# Telegram only lets a bot delete its own messages, and only ones younger than 48h.
# Every delete is therefore best-effort: a failure means "a stale screen remains",
# never a broken flow - so only genuinely unexpected faults are worth a warning.
_UNDELTABLE = ("message to delete not found", "message can't be deleted",
               "message_id_invalid", "chat_write_forbidden", "not enough rights")


def _is_private(chat) -> bool:
    """Absent .type (test doubles, minimal setups) counts as private."""
    return getattr(chat, "type", Chat.PRIVATE) == Chat.PRIVATE


def screen(ctx) -> dict | None:
    """The tracked screen, or None."""
    s = ctx.user_data.get(SCREEN_KEY)
    return s if isinstance(s, dict) and s.get("message_id") else None


def screen_id(ctx) -> int | None:
    s = screen(ctx)
    return int(s["message_id"]) if s else None


def is_screen(ctx, message_id) -> bool:
    """True when message_id is the live screen (i.e. editing it is visible)."""
    tracked = screen_id(ctx)
    return tracked is not None and message_id is not None and int(message_id) == tracked


def set_screen(ctx, chat_id: int, message_id: int) -> None:
    ctx.user_data[SCREEN_KEY] = {"chat_id": int(chat_id), "message_id": int(message_id)}


def clear_screen(ctx) -> None:
    ctx.user_data.pop(SCREEN_KEY, None)


async def drop_screen(ctx, bot) -> bool:
    """Delete the tracked screen. Always forgets it, delete or not."""
    s = screen(ctx)
    clear_screen(ctx)
    if not s:
        return False
    try:
        await bot.delete_message(chat_id=int(s["chat_id"]), message_id=int(s["message_id"]))
    except Exception as e:
        if not any(m in str(e).lower() for m in _UNDELTABLE):
            log.warning("screen delete failed: %s", e)
        return False
    return True


async def _send(ctx, chat_id: int, text: str, reply_markup) -> object:
    return await ctx.bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup)


async def _send_screen(ctx, chat_id: int, text: str, reply_markup) -> str:
    try:
        msg = await _send(ctx, chat_id, text, reply_markup)
    except Exception:
        log.exception("screen send failed")
        return FAILED
    mid = getattr(msg, "message_id", None)
    if mid is not None:
        set_screen(ctx, chat_id, mid)
    return SENT


async def render(update, ctx, text: str, reply_markup=None) -> str:
    """Show a screen view. Returns EDITED / UNCHANGED / SENT / FAILED.

    The caller stays responsible for answering the callback query, since several
    views answer with a user-facing toast instead of a bare dismiss.
    """
    chat = update.effective_chat
    if chat is None:
        return FAILED
    if not _is_private(chat):
        # A group surface would be shared by every member: never edit, never
        # delete, never track - just add the view.
        try:
            await _send(ctx, chat.id, text, reply_markup)
        except Exception:
            log.exception("group view send failed")
            return FAILED
        return SENT

    q = update.callback_query
    tapped = q.message.message_id if (q is not None and q.message is not None) else None
    if tapped is not None and is_screen(ctx, tapped):
        status = await safe_edit(q, text, reply_markup)
        if status in (EDITED, UNCHANGED):
            return status
        # The screen died under us (deleted by the user, or it turned out to be
        # media). Forgetting the pointer and re-sending beats showing nothing.
        clear_screen(ctx)
        return await _send_screen(ctx, chat.id, text, reply_markup)

    await drop_screen(ctx, ctx.bot)
    return await _send_screen(ctx, chat.id, text, reply_markup)
