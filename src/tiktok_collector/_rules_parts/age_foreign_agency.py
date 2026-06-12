"""年齢 + 外国語 + 事務所系 — 3 サブチェック。

  1. _age_ng(text) → 年齢検出
  2. _looks_like_foreign(text) → 「外国語/海外」
  3. 25 語の事務所/所属/ライバー系 + rules.agency_keywords → 「他事務所/所属系({hit})」
"""
from __future__ import annotations

from typing import Optional

from ._helpers import _age_ng, _looks_like_foreign, _contains_any, _load_extra_words


_AGENCY_WORDS: list[str] = [
    "所属", "事務所所属", "ライバー事務所", "公式ライバー", "認証ライバー",
    "seju", "asobinext", "vaz", "grove", "avex", "ppp studio", "luv", "studio15",
    "321inc", "live事務所", "liver office", "liveroffice", "マネージャー", "manager",
    "nextwave", "neobright", "palmu", "pococha", "17live", "イチナナ",
]


def check(text: str, rules) -> Optional[str]:
    r = _age_ng(text)
    if r:
        return r

    if _looks_like_foreign(text):
        return "外国語/海外"

    hit = _contains_any(text, _AGENCY_WORDS + _load_extra_words(rules, "agency_keywords"))
    if hit:
        return "他事務所/所属系(" + hit + ")"

    return None
