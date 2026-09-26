"""Telegram core: app bootstrap, admin guard, callback validation, in-place edits."""
from __future__ import annotations
import re
from telegram import Update
from telegram.ext import Application

_CALLBACK_RE = re.compile(r"^[a-z_]+:[A-Za-z0-9_\-:]+$")

# Telegram rejects a button whose callback_data exceeds 64 BYTES at creation time
# (BUTTON_DATA_INVALID), so this is a hard ceiling, not a style limit.
CALLBACK_MAX_BYTES = 64

EDITED = "edited"        # the message now shows the new content
UNCHANGED = "unchanged"  # identical text+markup: nothing to do, NOT an error
NO_TEXT = "no_text"      # target has media only -> edit_message_text is illegal
GONE = "gone"            # target deleted / older than Telegram keeps
FAILED = "failed"

# BadRequests that are part of normal operation, not bugs. Double-tapping a menu
# button, or tapping one on a photo, must never reach the user's error alert.
_HARMLESS_EDITS = {
    "not modified": UNCHANGED,
    "no text in the message": NO_TEXT,
    "message to edit not found": GONE,
    "message_id_invalid": GONE,
    "message identifier is not specified": GONE,
}


def is_admin(telegram_id: int, admin_ids: tuple[int, ...]) -> bool:
    return int(telegram_id) in set(admin_ids or ())


def admin_only(admin_ids: tuple[int, ...]):
    """Decorator for PTB handlers: blocks non-admins."""
    def deco(func):
        async def wrapper(update: Update, context, *a, **kw):
            uid = update.effective_user.id if update.effective_user else 0
            if not is_admin(uid, admin_ids):
                if update.effective_message:
                    await update.effective_message.reply_text("⛔️ دسترسی مجاز نیست.")
                return
            return await func(update, context, *a, **kw)
        return wrapper
    return deco


def validate_callback(data: str) -> bool:
    """Reject forged/oversized callbacks before any state change."""
    if not data or len(data.encode("utf-8")) > CALLBACK_MAX_BYTES:
        return False
    return bool(_CALLBACK_RE.match(data))


def _classify(exc: Exception) -> str | None:
    """Map a Telegram error to a benign status, or None if it is a real fault."""
    text = str(getattr(exc, "message", "") or exc).lower()
    for needle, status in _HARMLESS_EDITS.items():
        if needle in text:
            return status
    return None


async def safe_edit(query, text: str, reply_markup=None) -> str:
    """edit_message_text that survives the three BadRequests Telegram raises in
    normal use. Returns EDITED / UNCHANGED / NO_TEXT / GONE.

    UNCHANGED is the important one: re-tapping the button of the screen you are
    already looking at makes Telegram answer "Message is not modified", which is
    a no-op the user must never see as an error. Anything NOT on the harmless
    list is re-raised, so genuine faults still reach the error path.
    """
    if query is None:
        return FAILED
    try:
        await query.edit_message_text(text=text, reply_markup=reply_markup)
    except Exception as e:
        status = _classify(e)
        if status is None:
            raise
        return status
    return EDITED


async def safe_edit_markup(query, reply_markup=None) -> bool:
    """Swap or clear only the keyboard, leaving the text alone.

    Used to strip dead buttons off a stale message instead of leaving the user
    tapping something that no longer exists.
    """
    if query is None:
        return False
    try:
        await query.edit_message_reply_markup(reply_markup=reply_markup)
    except Exception as e:
        if _classify(e) is None:
            raise
        return False
    return True


def parse_callback(data: str) -> tuple[str, str]:
    action, _, arg = (data or "").partition(":")
    return action, arg


def build_app(token: str, post_init=None):
    """post_init: optional async callable(app) run once at startup (e.g. background tasks)."""
    if not token or token.startswith("PUT_"):
        raise RuntimeError("BOT_TOKEN is not configured. See config/.env.example")
    builder = Application.builder().token(token).rate_limiter(None)
    if post_init is not None:
        builder = builder.post_init(post_init)
    return builder.build()
