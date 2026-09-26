"""Keyboard + progress-bar builders. All human texts are parameters (defaults are
neutral English); each bot passes its own copy (see bot/texts.py)."""
from __future__ import annotations
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup


def phone_request_kb(label: str = "📱 Share phone number") -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [[KeyboardButton(label, request_contact=True)]],
        resize_keyboard=True, one_time_keyboard=True,
    )


def remove_kb():
    from telegram import ReplyKeyboardRemove
    return ReplyKeyboardRemove()

def progress_bar(done: int, total: int, width: int = 12) -> str:
    if total <= 0:
        return "░░░░░░░░░░░░ 0%"
    pct = max(0, min(100, round(done / total * 100)))
    filled = round(done / total * width)
    return f"{'█' * filled}{'░' * (width - filled)} {pct}%"


def split_text(text: str, limit: int = 4000) -> list[str]:
    """Split long text on line boundaries (hard-splitting overlong lines).
    Never returns [''] — empty input gives []."""
    if not (text or "").strip():
        return []
    chunks: list[str] = []
    cur = ""
    for line in text.splitlines():
        if len(line) > limit:
            if cur:
                chunks.append(cur)
                cur = ""
            chunks += [line[i:i + limit] for i in range(0, len(line), limit)]
        elif len(cur) + len(line) + 1 > limit:
            chunks.append(cur)
            cur = line
        else:
            cur = (cur + "\n" + line) if cur else line
    if cur:
        chunks.append(cur)
    return chunks


def episode_list_kb(episodes: list[dict], unlocked_upto: int, unit: str = "Episode") -> InlineKeyboardMarkup:
    """episodes: [{episode_no, title}]. unlocked_upto: max episode_no user may open.
    unit: word for 'episode' in the bot's language (e.g. 'اپیزود'). Empty unit is
    allowed: the label falls back to mark + number/title with no dangling gap."""
    unit = (unit or "").strip()

    def label(mark: str, no: int, title: str) -> str:
        head = f"{mark} {unit}".strip() if unit else mark
        return f"{head} {no}. {title[:24]}" if title else f"{head} {no}"

    rows = []
    for ep in episodes:
        no = int(ep["episode_no"])
        title = str(ep.get("title") or "").strip()
        if no <= unlocked_upto:
            mark = "✅" if no < unlocked_upto else "▶️"
            rows.append([InlineKeyboardButton(label(mark, no, title), callback_data=f"ep:{no}")])
        else:
            rows.append([InlineKeyboardButton(label("🔒", no, title), callback_data=f"locked:{no}")])
    return InlineKeyboardMarkup(rows)


def nav_kb(next_label: str, next_cb: str, back_cb: str | None = "menu:main",
           home_label: str = "🏠 Home") -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(next_label, callback_data=next_cb)]]
    if back_cb:
        rows.append([InlineKeyboardButton(home_label, callback_data=back_cb)])
    return rows and InlineKeyboardMarkup(rows)


def back_only_kb(back_cb: str = "menu:main", back_label: str = "🏠 Home") -> InlineKeyboardMarkup:
    """A lone escape hatch. Replaces the keyboard of a message whose own buttons
    went stale (deleted episode, deactivated course) so the user is never left
    tapping something that answers nothing."""
    return InlineKeyboardMarkup([[InlineKeyboardButton(back_label, callback_data=back_cb)]])

