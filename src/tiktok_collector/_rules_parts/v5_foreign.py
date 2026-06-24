"""v5 外国語キーワード + 中文スパム + ベトナム発音記号 + 繁体字 — 5 判定パス。

  1. 78 語の海外キーワード(taiwan/台湾/香港/中文/韓国/泰語/越南/インドネシア/
     マレーシア/シンガポール/越南固有の発音/babygirl/bikini/viral/foryou/
     東南アジア地名/手势舞/甜妹/白羊座 等) → 「外国語/海外({kw})」
  2. ハングル U+AC00-U+D7AF / タイ U+0E00-U+0E7F / キリル U+0400-U+04FF /
     アラビア U+0600-U+06FF → 「外国語/海外(文字種)」
  3. ベトナム語アクセント → 「外国語/海外(ベトナム語文字)」
  4. 中文スパム 17 語(置顶/找我/美女/漂亮/可爱/视频/比基尼/泳装 等)
     → 「外国語/海外({kw})」
  5. 繁体字 2 文字以上ヒット → 「外国語/海外(繁体字)」

入力: text — _candidate_text(candidate) の結果(lower 済み)。
判定 1 では小文字版と原文の両方をチェック(原文にはカナ・ハングルが含まれる)。
"""
from __future__ import annotations

import re

_V5_FOREIGN_KEYWORDS: list[str] = [
    "taiwan", "taipei", "台灣", "台湾", "臺灣",
    "香港", "hong kong", "hongkong",
    "china", "chinese", "中文", "繁體", "繁体", "中国語", "華語", "华语",
    "korea", "korean", "한국",
    "태국", "thai", "thailand",
    "philippines", "vietnam",
    "indonesia", "malaysia", "singapore",
    "overseas", "foreign", "foreigner",
    "xuhuong", "xuhuongtiktok", "xu huong", "xuhướng", "hướng",
    "gaixinh", "gaixinhtiktok", "gai xinh", "xinhdep", "xinh dep",
    "girlxinh", "nhactrung",
    "dungmai", "halinh",
    "babygirl", "bikini", "binkini",
    "viral", "trending", "foryou", "hottrend",
    "follow mình", "flow em", "follow tui", "mọi người", "giúp mình",
    "lên 1000fl", "1000fl", "vào đây", "tìm gì", "em rất", "cô đơn",
    "mình", "nhé", "nhá", "đi ạ", "tui",
    "置顶找我", "gaixinhmacbinkini",
    "australia", "perth", "single", "makefriends", "southern hemisphere", "freedom",
    "手势舞", "甜妹", "白羊座",
]

_NON_JP_SCRIPT_SET = re.compile(
    r"[가-힯฀-๿Ѐ-ӿ؀-ۿ]"
)
_VIETNAMESE_ACCENT = re.compile(
    r"[ăâêôơưđàáạảãằắặẳẵầấậẩẫèéẹẻẽềếệểễìíịỉĩòóọỏõồốộổỗờớợởỡùúụủũừứựửữỳýỵỷỹ]"
)

_V5_CHINESE_SPAM_KEYWORDS: list[str] = [
    "置顶", "找我", "美女", "漂亮", "可爱",
    "关注", "私信", "主页",
    "點", "點擊", "點我",
    "視頻", "视频",
    "比基尼", "泳裝", "泳装",
    # 中国語専用の生活・運勢・航空系ワード(日本語では使われない簡体字表現)
    "热门",    # 中国TikTok限定のトレンドタグ
    "空姐",    # 客室乗務員(中国語のみ、日本語ではCA/スチュワーデス)
    "空乘",    # キャビンクルー(中国語専用)
    "航班",    # フライト/便番号(中国語専用、日本語では「便」)
    "财神",    # 財神(簡体字、日本語では使わない)
    "财运",    # 金運(簡体字)
    "转运",    # 運気転換(簡体字の転)
]

_V5_TRADITIONAL_CHARS = "這裡妳們嗎沒麼個幾為點歡樂國學廣東臺灣說聽買賣開網寫氣體應覺讓從與給還發"


def check(text: str) -> str | None:
    text_lower = text.lower()

    # 1. 海外キーワード
    for kw in _V5_FOREIGN_KEYWORDS:
        if kw.lower() in text_lower or kw in text:
            return f"外国語/海外({kw})"

    # 2. 非日本語スクリプト(ハングル/タイ/キリル/アラビア)
    if _NON_JP_SCRIPT_SET.search(text):
        return "外国語/海外(文字種)"

    # 3. ベトナム語アクセント
    if _VIETNAMESE_ACCENT.search(text_lower):
        return "外国語/海外(ベトナム語文字)"

    # 4. 中文スパムキーワード
    for kw in _V5_CHINESE_SPAM_KEYWORDS:
        if kw in text:
            return f"外国語/海外({kw})"

    # 5. 繁体字 2 文字以上
    if sum(1 for ch in text if ch in _V5_TRADITIONAL_CHARS) >= 2:
        return "外国語/海外(繁体字)"

    return None
