"""未成年系 — 学校行事/学年/年齢正規表記の判定。

bio/hashtag/name/uid を結合したテキスト全体に対して、4 通りの未成年シグナルを
検出する。

  1. 学校行事/学年/年齢ワード(文化祭・体育祭・修学旅行・高一/二・中一/二/三・
     13/14/15/16/17歳(才/サイ/❤/♡/♥)・JK 関連の音/字面表記・11y〜17y)が含まれる
     → 「NGワード({word})」
  2. 括弧表記 (11)〜(17) / (11)〜(17) → 「未成年系NG(括弧年齢表記)」
  3. 11y〜17y(前後英数字なし) → 「未成年系NG(11y-17y)」
  4. 13〜17 + ハート絵文字(❤♡♥💕💖💗💓💞) → 「未成年系NG(年齢+ハート表記)」

入力:
  text — _candidate_text(candidate) の結果(uid/name/tags/bio などを空白結合 + lower 化済み)
"""
from __future__ import annotations

import re

_SCHOOL_AGE_WORDS: list[str] = [
    "文化祭", "体育祭", "修学旅行", "高二", "高一", "中三", "中二", "中一",
    "17歳", "17才", "17サイ", "17❤︎", "17❤", "17♡", "17♥",
    "16歳", "16才", "16サイ", "16❤︎", "16❤", "16♡", "16♥",
    "15歳", "15才", "15サイ", "15❤︎", "15❤", "15♡", "15♥",
    "14歳", "14才", "14サイ", "14❤︎", "14❤", "14♡", "14♥",
    "13歳", "13才", "13サイ", "13❤︎", "13❤", "13♡", "13♥",
    "えふじぇーしー", "えすじぇーしー", "えるじぇーしー", "えすじぇーけー", "えふじぇーけー",
    "11y", "12y", "13y", "14y", "15y", "16y", "17y",
]
_FULLWIDTH_TO_HALFWIDTH = str.maketrans("０１２３４５６７８９", "0123456789")
_PAREN_AGE = re.compile(r"[\(（]\s*(?:11|12|13|14|15|16|17)\s*[\)）]")
_AGE_Y_SUFFIX = re.compile(r"(?<![a-zA-Z0-9])(?:11|12|13|14|15|16|17)\s*y(?![a-zA-Z0-9])")
_AGE_HEART = re.compile(r"(?<!\d)(?:13|14|15|16|17)\s*[❤♡♥💕💖💗💓💞]")


def check(text: str) -> str | None:
    norm = str(text or "").translate(_FULLWIDTH_TO_HALFWIDTH)
    low = norm.lower()

    for w in _SCHOOL_AGE_WORDS:
        ws = str(w or "").strip()
        if ws and ws.lower() in low:
            return f"NGワード({ws})"

    if _PAREN_AGE.search(norm):
        return "未成年系NG(括弧年齢表記)"
    if _AGE_Y_SUFFIX.search(low):
        return "未成年系NG(11y-17y)"
    if _AGE_HEART.search(norm):
        return "未成年系NG(年齢+ハート表記)"
    return None
