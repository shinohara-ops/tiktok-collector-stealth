"""色付き漏れ v2 — ワードリスト + タグコンボ 判定。

色付きマークされたアカウントの傾向から逆引きで作られた v2 補強リスト。
6 判定パスを順番に走る:

  1. 48 ワード NG リスト(Doublefedora / mafioso / ベトナムフェスティバル /
     可愛い女の子 / 宝鐘マリン / cosplay / lingerie / カラコン / じゅんな 等)
     ※ litlink/lit.link はリスト含有でも判定対象外
     → 「NGワード({word})」
  2. 外部リンク(facebook.com / mibextid / onlyfans / ofans / fansly)
     ただし text に litlink/lit.link を含むなら除外しない
     → 「外部リンクNG({link})」
  3. Bio 空欄 + 英字のみタグ(日本語なし) → 「外国語/海外(英字タグのみ/プロフィール紹介文空欄)」
  4. Bio 空欄 + タグに "fyp" → 「プロフィール紹介文空欄(fyp)」
  5. Bio 空欄 + タグ全体が "可愛" or "可愛い" 単独 → 「ハッシュタグ単体NG(可愛)」
  6. タグに "可愛い" AND "女の子" → 「ハッシュタグNG(可愛い女の子)」

入力:
  text — _candidate_text(candidate) の結果。lower 化はモジュール内で行う。
  bio_s — _cs_bio_s
  tags — _cs_tags

Sheets 連動の scoped NG 判定はここでは扱わない(呼び出し側で続けて評価)。
"""
from __future__ import annotations

import re

_LEAK_V2_WORDS: list[str] = [
    "Doublefedora", "mafioso", "forsaken",
    "ベトナムフェスティバル", "ウエノデコリアンフェスタ", "コリアンフェスタ",
    "カリブラテンアメリカストリート", "ラテンアメリカ",
    "日比谷音楽祭", "アウトドアシネマ",
    "スタンダップコメディ", "standupcomedy", "crowdwork",
    "ほんまやでダンス", "newmusic", "いいねください",
    "fypツ", "smail",
    "facebook.com", "mibextid",
    "可愛い女の子", "毎日 可愛い女の子",
    "宝鐘マリン",
    "くださいませチャレンジ", "愛くださいませ",
    "成熟した女性", "成熟",
    "cosplay", "cosplayer",
    "neongenesisevangelion", "アスカ",
    "lingerie", "gorgeous",
    "MagneticBeauty", "SelfLoveVibes", "GlamAndGrow", "ConfidenceIsKey",
    "PR エバーカラー", "エバーカラー", "カラコン",
    "ROWfreelove", "rowlove", "rowbuzz",
    "charlesandsylvia", "wolfieandsylvia", "couplescomedy",
    "じゅんな", "ゆうな",
]

_EXTERNAL_LINKS: list[str] = [
    "facebook.com", "mibextid", "onlyfans", "ofans", "fansly",
]

_TAGS_HAS_JAPANESE = re.compile(r"[ぁ-んァ-ヶ一-龥]")
_TAGS_HAS_ASCII = re.compile(r"[a-zA-Z]")


def check(text: str, bio_s: str, tags: str) -> str | None:
    text_lower = text.lower()
    has_litlink = ("lit.link" in text_lower) or ("litlink" in text_lower)

    # 1. 48-word leak v2 list
    for w in _LEAK_V2_WORDS:
        ws = str(w or "").strip()
        if not ws:
            continue
        if ws.lower() in ("litlink", "lit.link"):
            continue
        if ws.lower() in text_lower:
            return f"NGワード({ws})"

    # 2. External link gate
    for link in _EXTERNAL_LINKS:
        if link in text_lower and not has_litlink:
            return f"外部リンクNG({link})"

    tags_lower = tags.lower()

    # 3. Bio 空欄 + 英字のみタグ
    if bio_s == "" and tags:
        has_japanese = _TAGS_HAS_JAPANESE.search(tags) is not None
        has_ascii_letter = _TAGS_HAS_ASCII.search(tags) is not None
        if has_ascii_letter and not has_japanese:
            return "外国語/海外(英字タグのみ/プロフィール紹介文空欄)"

    # 4. Bio 空欄 + fyp タグ
    if bio_s == "" and "fyp" in tags_lower:
        return "プロフィール紹介文空欄(fyp)"

    # 5. Bio 空欄 + タグ全体が 可愛/可愛い
    if bio_s == "" and tags.strip() in ("可愛", "可愛い"):
        return "ハッシュタグ単体NG(可愛)"

    # 6. タグに 可愛い + 女の子
    if "可愛い" in tags and "女の子" in tags:
        return "ハッシュタグNG(可愛い女の子)"

    return None
