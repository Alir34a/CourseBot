"""Safe logging: redacts secrets, never logs tokens/phones/keys verbatim."""
from __future__ import annotations
import logging
import re

_PATTERNS = [
    re.compile(r"\d{9,}:AA[A-Za-z0-9_-]{30,}"),          # telegram bot token
    re.compile(r"(?i)(api[_-]?key|secret|password)\s*[:=]\s*\S+"),
    re.compile(r"\+?98\s?9\d{2}\s?\d{3}\s?\d{4}"),        # IR mobile
    re.compile(r"\b09\d{9}\b"),
]


def redact(text: str) -> str:
    out = str(text)
    for rx in _PATTERNS:
        out = rx.sub("[REDACTED]", out)
    return out


class _RedactFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            record.msg = redact(record.getMessage())
            record.args = ()
        except Exception:
            pass
        return True


def get_logger(name: str, level: str = "INFO") -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        h = logging.StreamHandler()
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        logger.addHandler(h)
    logger.addFilter(_RedactFilter())
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    return logger


def user_error(public_msg: str, log: logging.Logger, exc: BaseException | None = None) -> str:
    """Log technical detail, return user-friendly message."""
    if exc is not None:
        log.exception(redact(f"internal error: {exc}"))
    return public_msg
