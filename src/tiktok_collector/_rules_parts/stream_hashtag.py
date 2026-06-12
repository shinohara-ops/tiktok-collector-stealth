"""ライブ配信ワード + 08/09 ハッシュタグトークンの追加除外。

  1. 9 単語の配信系ワード(配信 / サブ配信 / テキーラ配信 / 本垢 / 本アカ /
     他にもあります 等)に部分一致 → 「NGワード({word})」
  2. ハッシュタグ列内のトークンに "08" / "09" が単体で現れる
     → 「ハッシュタグNG(08)」/「ハッシュタグNG(09)」

入力(_cs_* の strip 済み): uid_s, name_s, bio_s, tags
"""
from __future__ import annotations

import re

_STREAM_WORDS: list[str] = [
    "配信", "ｻﾌﾞ配信", "サブ配信", "配信専用", "テキーラ配信",
    "本垢", "本アカ", "本アカウント",
    "他にもあります",
]

_FULLWIDTH_TO_HALFWIDTH = str.maketrans("０１２３４５６７８９", "0123456789")
_TAG_TOKEN_SPLIT = re.compile(r"[#＃\s,，、/／｜|・.．。:_\-－ー]+")


def check(uid_s: str, name_s: str, bio_s: str, tags: str) -> str | None:
    full = " ".join([uid_s, name_s, tags, bio_s])
    full_lower = full.lower()

    for w in _STREAM_WORDS:
        ws = str(w or "").strip()
        if ws and ws.lower() in full_lower:
            return f"NGワード({ws})"

    tags_norm = tags.translate(_FULLWIDTH_TO_HALFWIDTH)
    tokens = [t for t in _TAG_TOKEN_SPLIT.split(tags_norm) if t]
    if "08" in tokens:
        return "ハッシュタグNG(08)"
    if "09" in tokens:
        return "ハッシュタグNG(09)"

    return None
