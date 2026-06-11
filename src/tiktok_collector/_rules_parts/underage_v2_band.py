"""未成年系 (v2 帯) — シャドバン / CapCut / 流行りダンス系ワード + 08/09 ペア・単独 再判定。

時系列で後から追加されたバージョン違い(v2)の追加除外ブロック。
最初の検出: シャドバン / CapCut / 流行りダンス / unsunghero / runaar 等の 9 ワード
が text 全体に含まれていれば即除外。

つづいて、underage_pair と同じ 08/09 ペア表記 + 単独表記の判定を **もう一度**
回す。なぜ重複しているかというと、この v2 ブロックは元 collector が後から追加した
追加 NG で、最初の underage_pair セクションを通過した候補に対して念のため再
チェックする意図がある(token 分割条件は同じだが、結合元の text を作り直して
いるため、稀に異なる結果になる可能性があった)。判定順を維持するためここでは
重複を温存する。

入力(呼び出し側で _cs_* 系の strip 済み値を渡す):
  uid_s, name, bio_s, tags
"""
from __future__ import annotations

import re

_V2_BAND_WORDS: list[str] = [
    "シャドバン",
    "シャドウバン",
    "げろげろぴー",
    "capcut",
    "tiktok流行りダンス",
    "流行りダンス",
    "流行りdance",
    "unsunghero",
    "runaar",
]

_FULLWIDTH_TO_HALFWIDTH = str.maketrans("０１２３４５６７８９", "0123456789")
_PAIR_PATTERN = re.compile(
    r"(?<!\d)(?:08|09)\s*[♡❤♥💕💖/／・,，、.．\-－_\s]+\s*(?:08|09)(?!\d)"
)
_TOKEN_SPLIT_PATTERN = re.compile(r"[#＃\s,，、/／｜|・.．。:_\-－ー♡❤♥💕💖]+")


def check(uid_s: str, name: str, bio_s: str, tags: str) -> str | None:
    full = " ".join([uid_s, str(name or ""), tags, bio_s])
    low = full.lower()

    for w in _V2_BAND_WORDS:
        ws = str(w or "").strip()
        if ws and ws.lower() in low:
            return f"NGワード({ws})"

    digit_text = full.translate(_FULLWIDTH_TO_HALFWIDTH)
    if _PAIR_PATTERN.search(digit_text):
        return "未成年系NG(08/09ペア表記)"
    tokens = [t for t in _TOKEN_SPLIT_PATTERN.split(digit_text) if t]
    if "08" in tokens:
        return "未成年系NG(08)"
    if "09" in tokens:
        return "未成年系NG(09)"
    return None
