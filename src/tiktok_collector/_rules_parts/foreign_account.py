"""外国語/海外アカウント — ベトナム/中文/韓国語/英文 の追加判定。

「日本以外のアカウントは取らない」方針を強化するための追加除外。9 判定パスを
順番に走らせる。判定順を保つこと:

  1. 18 ワードハードコード(ベトナム/英字/インドネシア系の頻出語) → 「外国語/海外({word})」
  2. 31 中国語フレーズ → 「外国語/海外(中国語:{phrase})」
  3. 簡体字 2 文字以上 → 「外国語/海外(中国語/簡体字)」
  4. Bio に簡体字 + 日本語かな無し → 「外国語/海外(中国語/簡体字Bio)」
  5. 非日本語文字種(ミャンマー/クメール/ラオス/タイ/キリル/アラビア/デーヴァナーガリー)
     → 「外国語/海外(非日本語文字種)」
  6. ベトナム語アクセント → 「外国語/海外(ベトナム語文字)」
  7. 英語文章 Bio → 「外国語/海外(英語文章Bio)」
  8. 日本語なし + 全体が英語文章っぽい → 「外国語/海外(英語文章)」
  9. ハングル 10 文字以上 or トークン 3 以上 → 「外国語/海外(韓国語文章)」
     Bio に 6 文字以上 → 「外国語/海外(韓国語Bio)」

入力(_cs_* の strip 済み): uid_s, name_s, bio_s, tags
"""
from __future__ import annotations

import re

_NON_JP_WORDS: list[str] = [
    "feilvbin", "絡み募",
    "xuhuong", "xuhuongtiktok", "gaixinh", "gaixinhtiktok",
    "xinhdep", "cewek", "wanita", "masih mencari", "cantik", "mencari",
    "dungmai", "halinh", "babygirl", "bikini",
    "follow tui", "mọi người",
]

_CN_PHRASES: list[str] = [
    "今天", "也是", "被热", "热可可", "旧电影", "电影",
    "治愈", "的一天", "关注", "私信", "主页", "置顶", "找我",
    "美女", "漂亮", "可爱", "点赞", "评论", "转发", "粉丝", "视频",
    "熱門", "热门", "推荐",
    "大家好", "我是", "谢谢", "喜欢", "生活", "日常", "女孩", "女生",
]

_CN_SIMPLIFIED_CHARS: list[str] = [
    "这", "们", "为", "热", "电", "说", "话", "买", "卖",
    "体", "会", "觉", "让", "从", "给", "发", "欢", "乐",
    "国", "学", "广", "东", "网", "写", "气", "应", "旧",
    "后", "边", "过", "还", "进", "长", "门",
]

_NON_JP_SCRIPTS = re.compile(
    r"[က-႟ក-៿຀-໿฀-๿Ѐ-ӿ؀-ۿऀ-ॿ]"
)
_VIETNAMESE_ACCENT = re.compile(
    r"[ăâêôơưđàáạảãằắặẳẵầấậẩẫèéẹẻẽềếệểễìíịỉĩòóọỏõồốộổỗờớợởỡùúụủũừứựửữỳýỵỷỹ]"
)
_KANA_ONLY = re.compile(r"[ぁ-んァ-ヶ]")
_JP_HANZI_KANA = re.compile(r"[ぁ-んァ-ヶ一-龥]")
_HANGUL = re.compile(r"[가-힯]")
_HANGUL_TOKEN = re.compile(r"[가-힯]{2,}")

_ENGLISH_WORD = re.compile(r"[a-zA-Z']{2,}")
_ENGLISH_PUNCT = re.compile(r"[.!?]")
_ENGLISH_COMMON_WORDS: list[str] = [
    "i", "you", "we", "they", "he", "she",
    "my", "your",
    "the", "and", "to", "with", "for", "from",
    "like", "love",
    "dont", "don't", "cant", "can't", "can",
    "am", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had",
    "me", "at", "in", "on", "of",
    "small", "talk",
]


def _english_sentence_like(s: str) -> bool:
    low = str(s or "").lower()
    words = _ENGLISH_WORD.findall(low)
    if len(words) >= 6:
        return True
    hits = 0
    for ew in _ENGLISH_COMMON_WORDS:
        if re.search(r"\b" + re.escape(ew.lower()) + r"\b", low):
            hits += 1
    if len(words) >= 3 and hits >= 2:
        return True
    if len(words) >= 3 and _ENGLISH_PUNCT.search(s):
        return True
    return False


def check(uid_s: str, name_s: str, bio_s: str, tags: str) -> str | None:
    full = " ".join([uid_s, name_s, tags, bio_s])
    full_lower = full.lower()

    # 1. 18-word hardcoded list
    for w in _NON_JP_WORDS:
        ws = str(w or "").strip()
        if ws and ws.lower() in full_lower:
            return f"外国語/海外({ws})"

    # 2. Chinese phrases
    for p in _CN_PHRASES:
        if p and p in full:
            return f"外国語/海外(中国語:{p})"

    # 3 & 4. Simplified Chinese chars
    cn_simplified_hit = sum(1 for ch in _CN_SIMPLIFIED_CHARS if ch and ch in full)
    if cn_simplified_hit >= 2:
        return "外国語/海外(中国語/簡体字)"
    if bio_s and cn_simplified_hit >= 1 and not _KANA_ONLY.search(bio_s):
        return "外国語/海外(中国語/簡体字Bio)"

    # 5. Non-Japanese scripts
    if _NON_JP_SCRIPTS.search(full):
        return "外国語/海外(非日本語文字種)"

    # 6. Vietnamese accents
    if _VIETNAMESE_ACCENT.search(full_lower):
        return "外国語/海外(ベトナム語文字)"

    # 7 & 8. English sentence-like
    if _english_sentence_like(bio_s):
        return "外国語/海外(英語文章Bio)"
    if not _JP_HANZI_KANA.search(full) and _english_sentence_like(full):
        return "外国語/海外(英語文章)"

    # 9. Korean
    hangul_count = len(_HANGUL.findall(full))
    hangul_tokens = _HANGUL_TOKEN.findall(full)
    if hangul_count >= 10 or len(hangul_tokens) >= 3:
        return "外国語/海外(韓国語文章)"
    if bio_s and len(_HANGUL.findall(bio_s)) >= 6:
        return "外国語/海外(韓国語Bio)"

    return None
