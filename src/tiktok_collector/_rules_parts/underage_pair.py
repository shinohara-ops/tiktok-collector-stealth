"""未成年系 — 08/09 ペア表記 + 単独表記 の判定。

候補となる文字列(uid / display_name / hashtags / bio を結合し、全角→半角数字に
正規化した text)に「08/09」が出てくるかを 3 通りでチェックする。

  1. "08" と "09" が記号(♡ ❤ ♥ 💕 💖 / ・ , 、 . - _ 空白 等)を挟んで隣接
     → 「未成年系NG(08/09ペア表記)」
  2. トークン分割して "08" が単独で含まれる → 「未成年系NG(08)」
  3. 同様に "09" 単独 → 「未成年系NG(09)」

判定の入力は呼び出し側で組み立てた _cs_digit_text(全角数字を半角に置換済み)。
"""
from __future__ import annotations

import re

_PAIR_PATTERN = re.compile(
    r"(?<!\d)(?:08|09)\s*[♡❤♥💕💖/／・,，、.．\-－_\s]+\s*(?:08|09)(?!\d)"
)
_TOKEN_SPLIT_PATTERN = re.compile(r"[#＃\s,，、/／｜|・.．。:_\-－ー♡❤♥💕💖]+")


def check(cs_digit_text: str) -> str | None:
    """08/09 ペア表記または単独表記が検出されたら reason を返す。"""
    if _PAIR_PATTERN.search(cs_digit_text):
        return "未成年系NG(08/09ペア表記)"
    tokens = [t for t in _TOKEN_SPLIT_PATTERN.split(cs_digit_text) if t]
    if "08" in tokens:
        return "未成年系NG(08)"
    if "09" in tokens:
        return "未成年系NG(09)"
    return None
