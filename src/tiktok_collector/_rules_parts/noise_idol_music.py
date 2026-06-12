"""ノイズ/アイドル/音楽系タグ — daun muda / onephony / 反復ASCII / 田島櫻子 系。

「量産タグ/アイドル系/海外音楽系」と分類される候補をまとめて落とす追加除外。
5 判定パスを順番に走らせる。

  1. 11 ワード(daun muda / 田島櫻子 / onephony / slipknot / metal /
     don't like small talk / small talk 等)に部分一致 → 「NGワード({word})」
  2. ハッシュタグ内に同じ英字 8 文字以上連続 → 「ハッシュタグNG(同一英字連続)」
  3. fyp + ハッシュタグ内同じ英字 6 文字以上連続 → 「ハッシュタグNG(fyp+同一英字連続)」
  4. 日本語なし + ascii タグ + ascii Bio + Bio 30 字以下
     → 「外国語/海外(英字タグ+短文英字Bio)」
  5. Bio 空欄 + (onephony OR 田島櫻子 in tags)
     → 「アイドル/ファン系タグ(プロフィール紹介文空欄)」

入力(_cs_* の strip 済み): uid_s, name_s, bio_s, tags
"""
from __future__ import annotations

import re

_NOISE_WORDS: list[str] = [
    "daun muda", "daun", "muda",
    "田島櫻子", "田島櫻子ちゃん",
    "onephony", "slipknot", "metal",
    "don't like small talk", "dont like small talk", "small talk",
]

_REPEATED_ASCII_8 = re.compile(r"(?i)(?<![a-z])([a-z])\1{7,}(?![a-z])")
_REPEATED_ASCII_6 = re.compile(r"(?i)([a-z])\1{5,}")
_JP_HANZI_KANA = re.compile(r"[ぁ-んァ-ヶ一-龥]")
_ASCII_LETTER = re.compile(r"[a-zA-Z]")


def check(uid_s: str, name_s: str, bio_s: str, tags: str) -> str | None:
    full = " ".join([uid_s, name_s, tags, bio_s])
    full_lower = full.lower()
    tags_lower = tags.lower()

    # 1. ハードコード 11 ワード
    for w in _NOISE_WORDS:
        ws = str(w or "").strip()
        if ws and ws.lower() in full_lower:
            return f"NGワード({ws})"

    # 2. 同一英字連続(タグ)
    if _REPEATED_ASCII_8.search(tags):
        return "ハッシュタグNG(同一英字連続)"

    # 3. fyp + 短めの同一英字連続
    if "fyp" in tags_lower and _REPEATED_ASCII_6.search(tags):
        return "ハッシュタグNG(fyp+同一英字連続)"

    # 4. 日本語なし + ascii タグ + ascii Bio + 短文Bio
    has_japanese = _JP_HANZI_KANA.search(full) is not None
    if not has_japanese and _ASCII_LETTER.search(tags) and _ASCII_LETTER.search(bio_s):
        if len(bio_s) <= 30:
            return "外国語/海外(英字タグ+短文英字Bio)"

    # 5. Bio 空欄 + onephony / 田島櫻子 in tags
    if bio_s == "" and ("onephony" in tags_lower or "田島櫻子" in tags):
        return "アイドル/ファン系タグ(プロフィール紹介文空欄)"

    return None
