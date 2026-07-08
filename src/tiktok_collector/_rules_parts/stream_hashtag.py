"""ライブ配信ワード + 08/09 ハッシュタグトークンの追加除外。

  1. 9 単語の配信系ワード(配信 / サブ配信 / テキーラ配信 / 本垢 / 本アカ /
     他にもあります 等)に部分一致 → 「NGワード({word})」
  2. ハッシュタグ列内のトークンに "08" / "09" が単体で現れる
     → 「ハッシュタグNG(08)」/「ハッシュタグNG(09)」

入力(_cs_* の strip 済み): uid_s, name_s, bio_s, tags
"""
from __future__ import annotations

import re

from ._helpers import _contains_any

_STREAM_WORDS: list[str] = [
    "配信", "ｻﾌﾞ配信", "サブ配信", "配信専用", "テキーラ配信",
    "本垢", "本アカ", "本アカウント",
    "他にもあります",
    # ライブ配信系。`live` は短英字なので _contains_any 側で単語境界マッチになり、
    # `delivery` / `lively` / `believer` 等の誤爆を避ける。
    "live", "ライブ",
    # ライバー系(ポコチャライバー/tiktokライバー 等のハッシュタグで頻出)
    "ライバー", "ポコチャ",
    # 枠作り中/枠作り = 配信枠の準備中を意味する配信者表現
    "枠作り",
]

_FULLWIDTH_TO_HALFWIDTH = str.maketrans("０１２３４５６７８９", "0123456789")
_TAG_TOKEN_SPLIT = re.compile(r"[#＃\s,，、/／｜|・.．。:_\-－ー]+")
# bio 用: . - _ : は住所・日付・ハンドルに混入するため分割しない
_BIO_TOKEN_SPLIT = re.compile(r"[#＃\s,，、/／]+")


def check(uid_s: str, name_s: str, bio_s: str, tags: str) -> str | None:
    full = " ".join([uid_s, name_s, tags, bio_s])
    full_lower = full.lower()

    hit = _contains_any(full_lower, _STREAM_WORDS)
    if hit:
        return f"NGワード({hit})"

    tags_norm = tags.translate(_FULLWIDTH_TO_HALFWIDTH)
    tokens = [t for t in _TAG_TOKEN_SPLIT.split(tags_norm) if t]
    if "08" in tokens:
        return "ハッシュタグNG(08)"
    if "09" in tokens:
        return "ハッシュタグNG(09)"
    # 生まれ年(2010-2017)または年齢(10-17歳)を表す単独数字トークン
    for yr in ("10", "11", "12", "13", "14", "15", "16", "17"):
        if yr in tokens:
            return f"未成年系NG({yr})"

    # bio にも同じ数字が単独トークンとして現れる場合を検出
    # (住所 12-32 / 日付 2025.10.1 / ハンドル k_u3.16 を誤爆しないよう
    #  bio は . - _ : では分割せず space / # / 読点のみで分割する)
    if bio_s:
        bio_norm = bio_s.translate(_FULLWIDTH_TO_HALFWIDTH)
        bio_tokens = [t for t in _BIO_TOKEN_SPLIT.split(bio_norm) if t]
        for yr in ("10", "11", "12", "13", "14", "15", "16", "17"):
            if yr in bio_tokens:
                return f"未成年系NG({yr})"

    return None
