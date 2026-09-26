"""Shared Telegram test doubles.

One set of fakes for the whole suite instead of five hand-copied variants. The
important part is not the plumbing, it is that the doubles are *faithful* about
the two behaviours the screen model lives or dies on:

  * message_id is unique per chat and increases, so "is this the screen?" is a
    real question with a real answer;
  * edit_message_text raises "Message is not modified" when handed exactly what
    the message already shows, which is what Telegram does when a user
    double-taps. Tests therefore prove the bot swallows it instead of assuming it.

Run from the repo root: python -m pytest tests/ -q -p no:asyncio
"""

import asyncio
from types import SimpleNamespace

# ---------------------------------------------------------------- doubles


_MSG_SEQ = [1000]


class FakeMsg:
    """A message in a chat. Doubles as the incoming user message in tests.

    A message the bot owns carries `.bot`, so a reply lands in that chat's `live`
    map with a real id — which is what makes "the prompt is the newest message"
    an assertion instead of an assumption.
    """

    def __init__(self, text="", chat_id=0, message_id=None, reply_markup=None, bot=None):
        self.text = text
        self.chat_id = chat_id
        self.message_id = message_id
        self.reply_markup = reply_markup
        self.bot = bot
        self.sent = []
        self.photo = self.video = self.audio = None
        self.voice = self.video_note = self.document = None

    async def reply_text(self, text, reply_markup=None):
        self.sent.append((text, reply_markup))
        if self.bot is not None:
            return self.bot._mint(text, reply_markup)
        _MSG_SEQ[0] += 1
        return FakeMsg(text, self.chat_id, _MSG_SEQ[0], reply_markup=reply_markup)


def _same_markup(a, b):
    """Telegram compares the *resulting* message, so equal keyboards count as
    unchanged even when they are two distinct objects."""
    if a is None or b is None:
        return a is None and b is None
    try:
        return a.to_dict() == b.to_dict()
    except AttributeError:
        return a == b


class FakeQuery:
    """A callback query. `message` is the message whose button was tapped."""

    def __init__(self, data="", chat_id=0, message_id=None, bot=None):
        self.data = data
        self.chat_id = chat_id
        self.bot = bot
        # Reuse the chat's real message object when there is one, so consecutive
        # taps on the same button see each other's edits - which is what makes
        # "Message is not modified" reproducible instead of theoretical.
        held = bot.live.get(message_id) if (bot is not None and message_id is not None) else None
        self.message = held or FakeMsg("", chat_id, message_id, reply_markup=object(), bot=bot)
        if bot is not None and message_id is not None:
            bot.live.setdefault(message_id, self.message)
        self.answered = []
        self.edited = []
        self.markup_edits = []

    async def answer(self, *a, **k):
        self.answered.append((a, k))

    async def edit_message_text(self, text, reply_markup=None):
        held = self.message
        if held.photo or held.video or held.audio or held.voice or held.document:
            if not (held.text or "").strip():
                raise RuntimeError("Bad Request: there is no text in the message")
        if held.text == text and _same_markup(held.reply_markup, reply_markup):
            raise RuntimeError("Bad Request: Message is not modified")
        held.text = text
        held.reply_markup = reply_markup
        self.edited.append((text, reply_markup))
        return held

    async def edit_message_reply_markup(self, reply_markup=None):
        self.message.reply_markup = reply_markup
        self.markup_edits.append(reply_markup)
        return True


class FakeBot:
    """A bot bound to one chat.

    `live` mirrors the chat: every message the bot sent, by id. `bottom` is the
    newest one, i.e. what the user is looking at. An in-place edit changes
    `live` but never moves `bottom`; only a send does.
    """

    def __init__(self, chat_id=0, delete_fails=False):
        self.chat_id = chat_id
        self.delete_fails = delete_fails
        self.calls = []
        self.screens = []          # (text, markup) of every send_message
        self.deleted = []
        self.live = {}
        self._next_id = 100
        self.bottom = None

    def _mint(self, text="", reply_markup=None):
        mid = self._next_id
        self._next_id += 1
        self.bottom = mid
        msg = FakeMsg(text, self.chat_id, mid, reply_markup=reply_markup, bot=self)
        self.live[mid] = msg
        return msg

    async def send_message(self, chat_id=None, text="", reply_markup=None, **kw):
        self.calls.append(("message", text))
        self.screens.append((text, reply_markup))
        return self._mint(text, reply_markup)

    async def delete_message(self, chat_id=None, message_id=None):
        if self.delete_fails:
            raise RuntimeError("Bad Request: message can't be deleted")
        self.deleted.append(message_id)
        self.live.pop(message_id, None)
        if message_id == self.bottom:
            self.bottom = max(self.live) if self.live else None
        return True

    async def send_photo(self, chat_id=None, **kw):
        self.calls.append(("photo", kw.get("photo")))
    async def send_video(self, chat_id=None, **kw):
        self.calls.append(("video", kw.get("video")))
    async def send_audio(self, chat_id=None, **kw):
        self.calls.append(("audio", kw.get("audio")))
    async def send_voice(self, chat_id=None, **kw):
        self.calls.append(("voice", kw.get("voice")))
    async def send_video_note(self, chat_id=None, **kw):
        self.calls.append(("video_note", kw.get("video_note")))
    async def send_document(self, chat_id=None, **kw):
        self.calls.append(("document", kw.get("document")))


# ---------------------------------------------------------------- builders


def make_ctx(db, cfg, bot=None, user_data=None, job_queue=None):
    ctx = SimpleNamespace(application=SimpleNamespace(bot_data={"db": db, "cfg": cfg}),
                          user_data=user_data if user_data is not None else {}, bot=bot)
    if job_queue is not None:
        ctx.job_queue = job_queue
    return ctx


def make_update(uid, text="", query_data=None, bot=None, message_id=None, chat_id=None):
    chat_id = uid if chat_id is None else chat_id
    mid = message_id if message_id is not None else 0
    # In Telegram the message carrying a button IS update.effective_message, and
    # the bot owns it. Reusing the live object keeps reply_text in the same chat.
    held = bot.live.get(mid) if (bot is not None and mid) else None
    msg = held if held is not None else FakeMsg(text, chat_id, mid, bot=bot)
    if query_data is None:
        msg.text = text
    q = FakeQuery(query_data, chat_id, msg.message_id, bot) if query_data is not None else None
    return SimpleNamespace(effective_user=SimpleNamespace(id=uid, username=None),
                           effective_message=msg,
                           effective_chat=SimpleNamespace(id=chat_id, type="private"),
                           callback_query=q)


class Driver:
    """Walks one user's chat through real handlers the way a person would: the
    button is always tapped on the message currently at the bottom of the chat.

    `bot.bottom` is that bottom line, which is what makes "browsing costs zero
    new messages" an assertion instead of a hope.
    """

    def __init__(self, db, cfg, uid, job_queue=None, delete_fails=False):
        self.db, self.cfg, self.uid = db, cfg, uid
        self.bot = FakeBot(chat_id=uid, delete_fails=delete_fails)
        self.ctx = make_ctx(db, cfg, self.bot, job_queue=job_queue)

    def run(self, handler, text="", data=None):
        u = make_update(self.uid, text, data, self.bot, message_id=self.bot.bottom)
        asyncio.run(handler(u, self.ctx))
        return u

    def run_raw(self, handler, *args):
        """Call a handler that takes (update, ctx, ...) with extra args."""
        u = make_update(self.uid, data=None, bot=self.bot, message_id=self.bot.bottom)
        asyncio.run(handler(u, self.ctx, *args))
        return u

    @property
    def message_count(self):
        """How many bot messages this chat has ever received."""
        return self.bot._next_id - 100

    @property
    def live_count(self):
        """How many are still in the chat after deletions."""
        return len(self.bot.live)

    @property
    def bottom(self):
        return self.bot.live.get(self.bot.bottom)

    def tap(self, data):
        """Press a button and return the text now shown at the bottom."""
        self.run(_on_callback, data=data)
        return (self.bottom.text if self.bottom else None)


async def _on_callback(update, ctx):
    from bot.handlers import on_callback
    await on_callback(update, ctx)


def screen_labels(markup):
    return [b.text for row in markup.inline_keyboard for b in row] if markup else []


def view_of(update, bot):
    """Whatever the bot last showed, whichever path it took: an in-place edit
    when the tap was on the screen, a new message otherwise."""
    if update is not None and update.callback_query is not None and update.callback_query.edited:
        return update.callback_query.edited[-1]
    if bot is not None and bot.screens:
        return bot.screens[-1]
    return None
