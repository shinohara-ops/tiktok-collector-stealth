"""類似アカウント除外 v1 — 5 サブチェック(外部リンク/アダルト/コスプレ/空Bio+ASCIIタグ/ランダムID)。

5 種類の類似シグナルを順番に判定。判定順は厳守。

  3. 外部リンク誘導(facebook.com / mibextid / onlyfans / ofans / fansly)
     ただし litlink / lit.link を含むアカウントは除外しない
     → 「外部リンクNG({link})」
  4. アダルト/美容/成熟系(22 ワード:lingerie/gorgeous/mature/成熟/色気/
     セクシー/大人/大人女子/big.ass/MagneticBeauty/SelfLoveVibes/beauty/glam 等)
     ただし "beauty" のみ「Bio 空欄 OR タグに英字あり」が追加条件
     → 「NGワード({word})」または「NGワード(beauty系)」
  5. コスプレ/アニメ/キャラ/ゲーム系(18 ワード:cosplay/コスプレ/レイヤー/
     宝鐘マリン/ホロライブ/アスカ/evangelion/エヴァ/fivem/gta/gtarp/
     ゲーム実況/gaming 等)
     → 「NGワード({word})」
  1. プロフ空欄 + 英字ハッシュタグのみ → 「外国語/海外(英字タグのみ/プロフィール紹介文空欄)」
  2. プロフ空欄 + ランダム ID 風(英字+数字混在、セパレータなし、6 文字以上)
     → 「ランダムID/プロフィール紹介文空欄」

入力(_cs_* の strip 済み): uid_s, name_s, bio_s, tags
"""
from __future__ import annotations

import re

_EXTERNAL_LINKS: list[str] = [
    "facebook.com", "mibextid", "onlyfans", "ofans", "fansly",
]

_ADULT_WORDS: list[str] = [
    "lingerie", "gorgeous",
    "mature", "maturewoman", "maturewomen",
    "成熟", "成熟した女性",
    "色気", "セクシー", "sexy",
    "大人", "大人女子", "大人ガーリー",
    "big.ass", "ass9855",
    "MagneticBeauty", "SelfLoveVibes", "GlamAndGrow", "ConfidenceIsKey",
    "beauty", "glam",
]

_COSPLAY_GAME_WORDS: list[str] = [
    "cosplay", "cosplayer", "コスプレ", "レイヤー",
    "宝鐘マリン", "ホロライブ", "hololive",
    "アスカ", "asuka",
    "neongenesisevangelion", "evangelion", "エヴァ", "エヴァンゲリオン",
    "fivem", "gta", "gtarp",
    "ゲーム実況", "gaming",
]

_TAG_HAS_JAPANESE = re.compile(r"[ぁ-んァ-ヶ一-龥]")
_TAG_HAS_ASCII = re.compile(r"[a-zA-Z]")
_UID_NON_ALNUM = re.compile(r"[^a-zA-Z0-9]")
_UID_LETTER = re.compile(r"[a-z]")
_UID_DIGIT = re.compile(r"[0-9]")


def check(uid_s: str, name_s: str, bio_s: str, tags: str) -> str | None:
    full = " ".join([uid_s, name_s, tags, bio_s])
    full_lower = full.lower()

    # 3. 外部リンク誘導(litlink/lit.link は除外しない)
    has_litlink = ("lit.link" in full_lower) or ("litlink" in full_lower)
    for link_ng in _EXTERNAL_LINKS:
        if link_ng in full_lower and not has_litlink:
            return f"外部リンクNG({link_ng})"

    # 4. アダルト/美容/成熟系
    for adult_w in _ADULT_WORDS:
        adult_s = str(adult_w or "").strip()
        if not adult_s:
            continue
        if adult_s.lower() == "beauty":
            if "beauty" in full_lower and (bio_s == "" or _TAG_HAS_ASCII.search(tags)):
                return "NGワード(beauty系)"
            continue
        if adult_s.lower() in full_lower:
            return f"NGワード({adult_s})"

    # 5. コスプレ/アニメ/ゲーム系
    for cg_w in _COSPLAY_GAME_WORDS:
        cg_s = str(cg_w or "").strip()
        if cg_s and cg_s.lower() in full_lower:
            return f"NGワード({cg_s})"

    # 1. プロフ空欄 + 英字ハッシュタグのみ
    if bio_s == "" and tags:
        has_japanese_tag = _TAG_HAS_JAPANESE.search(tags) is not None
        has_ascii_tag = _TAG_HAS_ASCII.search(tags) is not None
        if has_ascii_tag and not has_japanese_tag:
            return "外国語/海外(英字タグのみ/プロフィール紹介文空欄)"

    # 2. プロフ空欄 + ランダム ID 風
    uid_clean = _UID_NON_ALNUM.sub("", uid_s).lower()
    uid_has_letter = _UID_LETTER.search(uid_clean) is not None
    uid_has_digit = _UID_DIGIT.search(uid_clean) is not None
    uid_has_sep = ("_" in uid_s) or ("." in uid_s) or ("-" in uid_s)
    if (
        bio_s == ""
        and len(uid_clean) >= 6
        and uid_has_letter
        and uid_has_digit
        and not uid_has_sep
    ):
        return "ランダムID/プロフィール紹介文空欄"

    return None
