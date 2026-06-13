from __future__ import annotations

import re

_USER_DIGITS_RE = re.compile(r"^user\d{6,}$")


def check(uid: str) -> str | None:
    if uid and _USER_DIGITS_RE.match(uid.strip().lower()):
        return "user始まり数字ID(デフォルト名)"
    return None
