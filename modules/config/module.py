"""Generic env-based configuration. No bot-specific logic hard-coded.

Reused by every future bot: copy config/.env.example -> .env and adjust.
"""
from __future__ import annotations
import os
from dataclasses import dataclass, field

try:
    from dotenv import load_dotenv  # optional
    load_dotenv()
except Exception:
    pass

DEFAULT_SENTINELS = {
    "BOT_TOKEN": {"PUT_YOUR_BOT_TOKEN_HERE", ""},
    "OWNER_EMAIL": {"owner@example.com", ""},
}


@dataclass(frozen=True)
class Config:
    bot_token: str = ""
    admin_ids: tuple[int, ...] = ()
    admin_usernames: tuple[str, ...] = ()
    owner_email: str = ""
    database_path: str = "data/bot.db"
    database_url: str = ""
    course_slug: str = "sample-course"
    course_title: str = "Sample course"
    episode_count: int = 15
    offer_trigger: str = "episode:15"
    offer_url: str = "https://example.com/buy"
    sales_webhook_secret: str = "CHANGE_ME"
    env: str = "development"
    log_level: str = "INFO"


def _parse_ids(raw: str) -> tuple[int, ...]:
    out: list[int] = []
    for tok in (raw or "").replace(";", ",").split(","):
        tok = tok.strip()
        if tok.isdigit():
            out.append(int(tok))
    return tuple(out)


def load_config(env: dict | None = None) -> Config:
    e = env if env is not None else os.environ
    return Config(
        bot_token=e.get("BOT_TOKEN", ""),
        admin_ids=_parse_ids(e.get("ADMIN_IDS", "")),
        admin_usernames=tuple(u.strip().lstrip("@") for u in (e.get("ADMIN_USERNAMES", "") or "").split(",") if u.strip()),
        owner_email=e.get("OWNER_EMAIL", ""),
        database_path=e.get("DATABASE_PATH", "data/bot.db"),
        database_url=e.get("DATABASE_URL", ""),
        course_slug=e.get("COURSE_SLUG", "sample-course"),
        course_title=e.get("COURSE_TITLE", "Sample course"),
        episode_count=int(e.get("EPISODE_COUNT", "15") or 15),
        offer_trigger=e.get("OFFER_TRIGGER", "episode:15"),
        offer_url=e.get("OFFER_URL", "https://example.com/buy"),
        sales_webhook_secret=e.get("SALES_WEBHOOK_SECRET", "CHANGE_ME"),
        env=e.get("ENV", "development"),
        log_level=e.get("LOG_LEVEL", "INFO"),
    )


def is_owner_configured(cfg: Config) -> dict[str, bool]:
    """Report which owner values are still defaults (never claim done otherwise)."""
    return {
        "bot_token": cfg.bot_token not in DEFAULT_SENTINELS["BOT_TOKEN"],
        "admin_ids": len(cfg.admin_ids) > 0,
        "owner_email": cfg.owner_email not in DEFAULT_SENTINELS["OWNER_EMAIL"],
    }


def require_config(cfg: Config) -> None:
    missing = [k for k, ok in is_owner_configured(cfg).items() if not ok]
    if missing:
        raise RuntimeError(f"Missing owner configuration: {', '.join(missing)}. See config/.env.example")
