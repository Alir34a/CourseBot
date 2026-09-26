"""Contact-based phone registration. Rejects typed numbers, validates IR mobiles."""
from __future__ import annotations
import re

_IR_RE = re.compile(r"^09\d{9}$")


def is_contact_message(msg) -> bool:
    return bool(getattr(msg, "contact", None))


def normalize_ir_mobile(raw: str) -> str | None:
    if not raw:
        return None
    d = re.sub(r"\D", "", raw)
    if d.startswith("98") and len(d) == 12:
        d = "0" + d[2:]
    if d.startswith("+98"):
        d = "0" + d[3:]
    d = d.replace(" ", "")
    return d if _IR_RE.match(d) else None


def validate_and_save(db, user_id: int, contact_phone: str, contact_user_id: int, owner_telegram_id: int) -> tuple[bool, str]:
    """Security: contact must belong to the sender (no spoofed numbers)."""
    if int(contact_user_id) != int(owner_telegram_id):
        return False, "لطفاً شماره موبایل خودت رو با دکمه «📱 ثبت شماره موبایل» ارسال کن."
    norm = normalize_ir_mobile(contact_phone)
    if not norm:
        return False, "شماره موبایل معتبر نیست. لطفاً با دکمه زیر دوباره ارسال کن."
    from modules.users import set_phone
    set_phone(db, user_id, norm)
    return True, norm
