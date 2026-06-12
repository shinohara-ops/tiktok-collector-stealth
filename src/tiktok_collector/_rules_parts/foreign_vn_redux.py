"""外国語/ベトナム語キーワード(再掲)+ 中文スパム — 3 判定パス。

v5_foreign と部分重複するが、判定順を保つためここでも別関数として置く。
ワードリストは v5 の Vietnamese サブセットと完全に重複しているが、リストの
順番や、_chinese_spam_keywords のセットが微妙に違うので個別に持つ。

  1. 39 語のベトナム語/外国語キーワード(text.lower() に部分一致)
     → 「外国語/海外({kw})」
  2. ベトナム語アクセント regex → 「外国語/海外(ベトナム語文字)」
  3. 16 語の中文スパム(text 原文に部分一致) → 「外国語/海外({kw})」

入力: text — _candidate_text(candidate) の結果(lower 済み)。
"""
from __future__ import annotations

import re

_FOREIGN_VN_KEYWORDS: list[str] = [
    "xuhuong", "xuhuongtiktok", "xu huong", "xuhướng", "hướng",
    "gaixinh", "gaixinhtiktok", "gai xinh", "xinhdep", "xinh dep",
    "girlxinh", "nhactrung", "dungmai", "halinh",
    "babygirl", "bikini", "binkini",
    "viral", "trending", "foryou", "hottrend",
    "follow mình", "flow em", "follow tui", "mọi người", "giúp mình",
    "lên 1000fl", "1000fl", "vào đây", "tìm gì", "em rất", "cô đơn",
    "mình", "nhé", "nhá", "đi ạ", "tui",
    "置顶找我", "gaixinhmacbinkini",
]

_VIETNAMESE_ACCENT = re.compile(
    r"[ăâêôơưđàáạảãằắặẳẵầấậẩẫèéẹẻẽềếệểễìíịỉĩòóọỏõồốộổỗờớợởỡùúụủũừứựửữỳýỵỷỹ]"
)

_CHINESE_SPAM_KEYWORDS: list[str] = [
    "置顶", "找我", "美女", "漂亮", "可爱",
    "关注", "私信", "主页",
    "點", "點擊", "點我",
    "視頻", "视频",
    "比基尼", "泳裝", "泳装",
]


def check(text: str) -> str | None:
    text_lower = text.lower()

    for kw in _FOREIGN_VN_KEYWORDS:
        if kw in text_lower:
            return f"外国語/海外({kw})"

    if _VIETNAMESE_ACCENT.search(text_lower):
        return "外国語/海外(ベトナム語文字)"

    for kw in _CHINESE_SPAM_KEYWORDS:
        if kw in text:
            return f"外国語/海外({kw})"

    return None
