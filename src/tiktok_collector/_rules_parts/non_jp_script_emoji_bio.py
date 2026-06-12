"""非日本語スクリプト + 絵文字のみ Bio + ASCII タグ — 3 種類の補強除外。

  1. 8-word(shit / お着替え / フェチ / fetish / ミニサイズ / パレオ 等)
     → 「NGワード({word})」
  2. ミャンマー(U+1000-U+109F)/ クメール(U+1780-U+17FF)/ ラオ(U+0E80-U+0EFF)
     のいずれかの文字を含む → 「外国語/海外(東南アジア系文字)」
  3. Bio が絵文字/記号のみ(英数字・かな・漢字なし) + タグに ASCII あり +
     タグに日本語なし → 「プロフィール紹介文が絵文字のみ/英字タグ」

入力(_cs_* の strip 済み): uid_s, name_s, bio_s, tags
"""
from __future__ import annotations

import re

_EXTRA_WORDS: list[str] = [
    "shit",
    "お着替え", "着替え", "着替えチャレンジ",
    "フェチ", "fetish",
    "ミニサイズ", "パレオ",
]

_BIO_HAS_MEANING_TEXT = re.compile(r"[a-zA-Z0-9ぁ-んァ-ヶ一-龥]")
_TAG_HAS_ASCII = re.compile(r"[a-zA-Z]")
_TAG_HAS_JAPANESE = re.compile(r"[ぁ-んァ-ヶ一-龥]")


def _has_sea_script_char(s: str) -> bool:
    for ch in s:
        c = ord(ch)
        # Myanmar / Khmer / Lao
        if 0x1000 <= c <= 0x109F:
            return True
        if 0x1780 <= c <= 0x17FF:
            return True
        if 0x0E80 <= c <= 0x0EFF:
            return True
    return False


def check(uid_s: str, name_s: str, bio_s: str, tags: str) -> str | None:
    full = " ".join([uid_s, name_s, tags, bio_s])
    full_lower = full.lower()

    for w in _EXTRA_WORDS:
        ws = str(w or "").strip()
        if ws and ws.lower() in full_lower:
            return f"NGワード({ws})"

    if _has_sea_script_char(full):
        return "外国語/海外(東南アジア系文字)"

    if bio_s:
        bio_has_meaning = _BIO_HAS_MEANING_TEXT.search(bio_s) is not None
        bio_is_emoji_only = not bio_has_meaning
        tags_has_ascii = _TAG_HAS_ASCII.search(tags) is not None
        tags_has_japanese = _TAG_HAS_JAPANESE.search(tags) is not None
        if bio_is_emoji_only and tags_has_ascii and not tags_has_japanese:
            return "プロフィール紹介文が絵文字のみ/英字タグ"

    return None
