"""色付き漏れ v1 — ワードリスト + タグコンボ 判定(v2 と部分重複)。

v2 と同じ 48 ワードリストを使うが、こちらは **litlink/lit.link バイパスがない**。
v2 では litlink を含むアカウントは「リンクツリー型なので海外スパムでない」と
免責されるが、v1 はそのバイパス無しで全件マッチ→除外する。

判定順:
  1. 48 ワード NG リスト(litlink バイパスなし)→ 「NGワード({word})」
  2. Bio 空欄 + 英字のみタグ(日本語なし) → 「外国語/海外(英字タグのみ/プロフィール紹介文空欄)」
  3. Bio 空欄 + タグに "fyp" → 「プロフィール紹介文空欄(fyp)」
  4. Bio 空欄 + タグ全体が "可愛" or "可愛い" → 「ハッシュタグ単体NG(可愛)」
  5. タグに "可愛い" AND "女の子" → 「ハッシュタグNG(可愛い女の子)」

ワードリストは colored_leak_v2_words から再利用してデータ重複を回避。

入力:
  text — _candidate_text(candidate) の結果
  bio_s — _cs_bio_s
  tags — _cs_tags
"""
from __future__ import annotations

import re

from .colored_leak_v2_words import _LEAK_V2_WORDS as _LEAK_V1_WORDS  # 同一のワードリストを共有

_TAGS_HAS_JAPANESE = re.compile(r"[ぁ-んァ-ヶ一-龥]")
_TAGS_HAS_ASCII = re.compile(r"[a-zA-Z]")


def check(text: str, bio_s: str, tags: str) -> str | None:
    text_lower = text.lower()

    # 1. 48-word leak v1 list(litlink バイパスなし)
    for w in _LEAK_V1_WORDS:
        ws = str(w or "").strip()
        if ws and ws.lower() in text_lower:
            return f"NGワード({ws})"

    tags_lower = tags.lower()

    # 2. Bio 空欄 + 英字のみタグ
    if bio_s == "" and tags:
        has_japanese = _TAGS_HAS_JAPANESE.search(tags) is not None
        has_ascii_letter = _TAGS_HAS_ASCII.search(tags) is not None
        if has_ascii_letter and not has_japanese:
            return "外国語/海外(英字タグのみ/プロフィール紹介文空欄)"

    # 3. Bio 空欄 + fyp タグ
    if bio_s == "" and "fyp" in tags_lower:
        return "プロフィール紹介文空欄(fyp)"

    # 4. Bio 空欄 + タグ全体が 可愛/可愛い
    if bio_s == "" and tags.strip() in ("可愛", "可愛い"):
        return "ハッシュタグ単体NG(可愛)"

    # 5. タグに 可愛い + 女の子
    if "可愛い" in tags and "女の子" in tags:
        return "ハッシュタグNG(可愛い女の子)"

    return None
