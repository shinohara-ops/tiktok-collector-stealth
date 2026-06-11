"""未成年系 — 08/09 末尾ID + 絵文字 Bio + テンプレ歌系タグ の判定。

2 通りの検出をする:

  1. テンプレ歌系の固定フレーズ(テンプレートお借りしました / 黒毛和牛上塩タン焼680円
     等)が text に含まれる → 「NGワード({word})」
     ※ similar_excluded のワードリストと一部重複するが、判定順を維持するためここに残す。
  2. unique_id が 08/09 で終わる + Bio が短文/絵文字のみ + テンプレ歌系のシグナル
     (テンプレ/お借りしました/この歌/歌好き/流行/capcut/落書き) が含まれる
     → 「未成年/量産系NG(08/09末尾ID+短文Bio+テンプレ歌系)」

入力(呼び出し側で計算済み):
  uid_s: unique_id を @ 除去・strip したもの
  name: display_name / nickname / name のいずれか(strip 不要)
  bio_s: Bio を strip したもの
  tags: ハッシュタグ列を空白結合して strip したもの
"""
from __future__ import annotations

import re

# テンプレ歌系の固定フレーズ。NGワード() で個別の単語名を返すために list で持つ。
_TEMPLATE_SONG_WORDS: list[str] = [
    "テンプレートお借りしました",
    "テンプレお借りしました",
    "この歌好き",
    "黒毛和牛上塩タン焼680円",
    "黒毛和牛上塩タン焼",
    "村谷はるな",
    "はるち",
]

_BIO_SYMBOL_STRIP = re.compile(r"[\W_\s]+", flags=re.UNICODE)
_TEMPLATE_SONG_SIGNAL = re.compile(
    r"(テンプレ|お借りしました|この歌|歌好き|流行り|流行|capcut|落書き)",
    flags=re.I,
)
_UID_08_09_TAIL = re.compile(r"(?:08|09)$")


def check(uid_s: str, name: str, bio_s: str, tags: str) -> str | None:
    full = " ".join([uid_s, str(name or ""), tags, bio_s])
    low = full.lower()

    for w in _TEMPLATE_SONG_WORDS:
        ws = str(w or "").strip()
        if ws and ws.lower() in low:
            return f"NGワード({ws})"

    # 08/09 末尾ID + 絵文字/短文Bio + テンプレ歌シグナル
    bio_without_symbols = _BIO_SYMBOL_STRIP.sub("", bio_s)
    emoji_or_too_short = (
        bio_s == ""
        or len(bio_without_symbols) == 0
        or len(bio_s) <= 2
    )
    template_song_like = _TEMPLATE_SONG_SIGNAL.search(full) is not None
    if _UID_08_09_TAIL.search(uid_s) and emoji_or_too_short and template_song_like:
        return "未成年/量産系NG(08/09末尾ID+短文Bio+テンプレ歌系)"
    return None
