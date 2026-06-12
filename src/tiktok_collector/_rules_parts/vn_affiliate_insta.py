"""ベトナム系ローマ字タグ / affiliate / Instagram 誘導 / メンションのみ Bio / K-POP タグ
の追加除外。

5 種類のシグナルを順番にチェック。判定順を保つこと。

  1. 13 ワード(vaycongchua / nangtho / bongiu 等のベトナム系/海外ローマ字タグ)
     → 「外国語/海外({word})」
  2. 12 ワード(いんすたきて / ID:/ID→ など SNS 誘導)
     → 「SNS誘導({word})」
  3. text 内に "affiliate" を含む → 「NGワード(affiliate)」
  4. fyp タグ + Bio に いんすた/インスタ/insta/instagram/id→/id:/id：
     → 「SNS誘導(fyp+インスタID)」
  5. Bio が `@xxx` だけ等、メンション単体で短い(4 文字以下)
     → 「プロフィール紹介文が短すぎるメンションのみ」
  6. cortis タグ + Bio 5 文字以下 → 「海外/ノイズタグ(cortis)」

入力(_cs_* の strip 済み): uid_s, name_s, bio_s, tags
"""
from __future__ import annotations

import re

_VN_LATIN_WORDS: list[str] = [
    "vaycongchua", "phongcachphap", "bachnguyetquang", "stylenangtho", "nangtho",
    "outfitlangman", "langman",
    "vay", "congchua", "phongcach",
    "bong_iu", "bongiu",
    "hihi",
]

_SNS_INVITE_WORDS: list[str] = [
    "affiliatemarketing", "affiliate marketing",
    "いんすたきて", "インスタきて", "インスタ来て",
    "instaきて", "instagramきて", "いんすた来て",
    "ID→", "id→", "ID:", "id:",
]

_FYP_INSTA_BIO_PATTERN = re.compile(
    r"(いんすた|インスタ|insta|instagram|id\s*[→:：])"
)
_MENTION_ONLY_PATTERN = re.compile(r"@?[a-zA-Z0-9_.]{1,20}")


def check(uid_s: str, name_s: str, bio_s: str, tags: str) -> str | None:
    full = " ".join([uid_s, name_s, tags, bio_s])
    full_lower = full.lower()
    tags_lower = tags.lower()
    bio_lower = bio_s.lower()

    # 1. ベトナム系/海外ローマ字タグ
    for w in _VN_LATIN_WORDS:
        ws = str(w or "").strip()
        if ws and ws.lower() in full_lower:
            return f"外国語/海外({ws})"

    # 2. SNS 誘導
    for w in _SNS_INVITE_WORDS:
        ws = str(w or "").strip()
        if ws and ws.lower() in full_lower:
            return f"SNS誘導({ws})"

    # 3. affiliate
    if "affiliate" in full_lower:
        return "NGワード(affiliate)"

    # 4. fyp + Insta ID 誘導
    if "fyp" in tags_lower and _FYP_INSTA_BIO_PATTERN.search(bio_lower):
        return "SNS誘導(fyp+インスタID)"

    # 5. メンションのみ Bio
    mention_only = re.fullmatch(_MENTION_ONLY_PATTERN, bio_s or "") is not None
    if mention_only and len(bio_s.replace("@", "").strip()) <= 4:
        return "プロフィール紹介文が短すぎるメンションのみ"

    # 6. cortis タグ単体 + Bio 短文
    for w in ("cortis",):
        ws = str(w or "").strip()
        if ws and ws.lower() in tags_lower and len(bio_s) <= 5:
            return f"海外/ノイズタグ({ws})"

    return None
