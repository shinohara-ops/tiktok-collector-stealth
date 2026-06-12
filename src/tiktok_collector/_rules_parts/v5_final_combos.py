"""v5 ハッシュコンボ + 数字のみタグ + 空 Bio/タグ — 最終 3 判定。

local_skip_reason の末尾。ここを抜けたら return None で関数完走。

  1. ハッシュタグに「美人」「モデル」「かわいい」が全部入る
     → 「ハッシュタグNG(美人/モデル/かわいい)」
  2. Bio が空 + ハッシュタグが非空 + 全角→半角に正規化したタグが
     記号/空白除去後すべて数字 → 「ハッシュタグ数字のみ/プロフィール紹介文空欄」
  3. Bio が空 + ハッシュタグが空 → 「ハッシュタグ/プロフィール紹介文空欄」

入力(_cs_* の strip 済み): bio_s, tags
"""
from __future__ import annotations

import re
from typing import Optional


_HASHTAG_TRIPLE: list[str] = ["美人", "モデル", "かわいい"]
_FULLWIDTH_TO_HALFWIDTH = str.maketrans("０１２３４５６７８９", "0123456789")
_TAG_DELIM = re.compile(r"[#＃\s,，、/／｜|・.．。:_\-－ー]+")


def check(bio_s: str, tags: str) -> Optional[str]:
    # 1. ハッシュタグ 3 点セット
    if all(kw in tags for kw in _HASHTAG_TRIPLE):
        return "ハッシュタグNG(美人/モデル/かわいい)"

    # 2. 数字のみタグ + Bio 空
    tags_norm = tags.translate(_FULLWIDTH_TO_HALFWIDTH)
    tags_digits_only = _TAG_DELIM.sub("", tags_norm)
    if bio_s == "" and tags != "" and tags_digits_only.isdigit():
        return "ハッシュタグ数字のみ/プロフィール紹介文空欄"

    # 3. タグも Bio も両方空
    if bio_s == "" and tags == "":
        return "ハッシュタグ/プロフィール紹介文空欄"

    return None
