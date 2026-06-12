"""年齢 + 外国語 + 事務所系 — 3 サブチェック。

  1. _age_ng(text) で年齢検出 → そのまま reason 返す
  2. _looks_like_foreign(text) で外国語/海外シグナル → 「外国語/海外」
  3. 25 語の事務所/所属/ライバー系 + rules.agency_keywords →
     「他事務所/所属系({hit})」

DI: age_ng_fn / looks_like_foreign_fn / contains_any_fn / load_extra_words_fn
"""
from __future__ import annotations

from typing import Optional


_AGENCY_WORDS: list[str] = [
    "所属", "事務所所属", "ライバー事務所", "公式ライバー", "認証ライバー",
    "seju", "asobinext", "vaz", "grove", "avex", "ppp studio", "luv", "studio15",
    "321inc", "live事務所", "liver office", "liveroffice", "マネージャー", "manager",
    "nextwave", "neobright", "palmu", "pococha", "17live", "イチナナ",
]


def check(text: str, rules, age_ng_fn, looks_like_foreign_fn, contains_any_fn, load_extra_words_fn) -> Optional[str]:
    r = age_ng_fn(text)
    if r:
        return r

    if looks_like_foreign_fn(text):
        return "外国語/海外"

    hit = contains_any_fn(text, _AGENCY_WORDS + load_extra_words_fn(rules, "agency_keywords"))
    if hit:
        return "他事務所/所属系(" + hit + ")"

    return None
