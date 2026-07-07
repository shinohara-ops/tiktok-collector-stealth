"""量産系 — ノイズタグ多数 + Bio 同一/空 の判定。

「テンプレ歌系・流行ダンス系」のノイズハッシュタグが多数並んでいるアカウントは
コンテンツ量産系と判断して除外する。3 通りで検出する。

  1. 08/09 末尾 ID + 短文(or 絵文字)Bio + ノイズタグ 1 つ以上
     → 「未成年/量産系NG(08/09末尾ID+短文Bio+{hit})」
  2. 短文(or 絵文字)Bio + ノイズタグ 2 つ以上
     → 「量産系NG(短文Bio+ノイズタグ複数)」
  3. ハッシュタグと Bio がほぼ同一 + ノイズタグ 1 つ以上
     → 「量産系NG(ハッシュタグとBio同一)」

入力は呼び出し側で計算済みの:
  - cs_low: 候補テキスト(uid/name/tags/bio)を結合して lower 化したもの
  - cs_uid_s: unique_id を @ 除去・strip したもの
  - cs_bio_empty_or_emoji: Bio が完全に空 or 絵文字記号のみ or 2 文字以下なら True
  - cs_tags: ハッシュタグ列を空白結合して strip したもの
  - cs_bio_s: Bio を strip したもの
"""
from __future__ import annotations

import re

# 量産系の目印になるノイズタグ群(テンプレ歌 / 流行ダンス / バズ狙い系)
_NOISE_TAGS: list[str] = [
    "capcut", "tiktok流行りダンス", "流行りダンス", "流行りdance",
    "落書き", "fyp", "fypシ", "おすすめ",
    "バズれ", "バズりたい", "テンプレ",
    "この歌", "この音源", "歌詞", "音源", "ダンス",
    "tiktok",
]

_UID_08_09_TAIL = re.compile(r"(?:08|09)$")
_WHITESPACE = re.compile(r"\s+")


def check(
    cs_low: str,
    cs_uid_s: str,
    cs_bio_empty_or_emoji: bool,
    cs_tags: str,
    cs_bio_s: str,
) -> str | None:
    generic_hit: str | None = None
    noise_count = 0
    for w in _NOISE_TAGS:
        ws = str(w or "").strip()
        if ws and ws.lower() in cs_low:
            noise_count += 1
            if generic_hit is None:
                generic_hit = ws

    if _UID_08_09_TAIL.search(cs_uid_s) and cs_bio_empty_or_emoji and generic_hit:
        return f"未成年/量産系NG(08/09末尾ID+短文Bio+{generic_hit})"

    if cs_bio_empty_or_emoji and noise_count >= 2:
        return "量産系NG(短文Bio+ノイズタグ複数)"

    tags_norm = _WHITESPACE.sub("", cs_tags.lower())
    bio_norm = _WHITESPACE.sub("", cs_bio_s.lower())
    if tags_norm and tags_norm == bio_norm and generic_hit:
        return "量産系NG(ハッシュタグとBio同一)"

    return None
