"""追加 NG ワード 2 — sexy / 感謝 / メンションスパム / 推し / bot / nidone 等。

  1. ["sexy", "japanese"](lower) → NGワード({w})
  2. "ありがとう" → NGワード(ありがとう)
  3. "メッセージ" → NGワード(メッセージ)
  4. 113 ワード一括(エロ/裏垢/抜き/動画販売/PayPay/推し活/ライバー/
     相互フォロー など) → NGワード({w})
  5. ["エロ","おかず","えろ","エドイ","えどい"] → NGワード({w})
  6. "推し" → NGワード(推し)
  7. ["動画売る","動画売ってます","秘密","ライブ"] (lower) → NGワード({w})
  8. ["bot","jp","live"] 単語境界マッチ(誤爆防止のため正規表現) → NGワード({w})
  9. ["にどね","ニドン","nidone","歓迎します","歓迎","孤独"] → NGワード({w})
"""
from __future__ import annotations

import re

_NG_SEXY_JP: list[str] = ["sexy", "japanese"]

# 113-word adult/livestream/promotion bulk list
_NG_ADULT_BULK: list[str] = [
    "えち", "えっち", "エッチ", "えちえち", "エロい", "えろい",
    "エロ垢", "裏垢", "裏アカ", "裏垢女子", "裏アカ女子", "裏垢男子",
    "せふれ", "セフレ", "オフパコ", "ぱこ", "パコ",
    "ぬき", "抜き", "抜ける", "抜いて",
    "おな", "オナ", "おなにー", "オナニー",
    "自慰", "性欲", "欲求不満",
    "むらむら", "ムラムラ", "むちむち", "むち",
    "下ネタ", "下着", "ランジェリー",
    "パンチラ", "胸チラ", "谷間",
    "おっぱい", "乳", "巨乳", "美乳",
    "尻", "お尻", "ケツ", "太もも", "脚フェチ",
    "動画販売", "動画売ります", "動画買って",
    "写真売ります", "写真販売", "個別販売",
    "PayPay", "ぺいぺい", "ペイペイ",
    "貢いで", "支援して",
    "見せ合い", "見せて", "見たい人", "欲しい人",
    "dmして", "DMして",
    "秘密垢", "限定公開", "限定動画", "鍵垢",
    "配信者", "ライバー", "ライブ配信", "LIVE配信", "live配信",
    "ファンマ", "推し活", "推して", "古参",
    "初見さん", "初見歓迎",
    "コメントして", "フォローして",
    "フォロバ", "相互", "相互フォロー",
]

_NG_ERO_GROUP: list[str] = ["エロ", "おかず", "えろ", "エドイ", "えどい"]
_NG_VIDEO_SALE_GROUP: list[str] = ["動画売る", "動画売ってます", "秘密", "ライブ"]
_NG_WORD_BOUNDARY: list[str] = ["bot", "jp", "live"]
_NG_NIDONE_GROUP: list[str] = ["にどね", "ニドン", "nidone", "歓迎します", "歓迎", "孤独"]


def check(text: str) -> str | None:
    text_lower = text.lower()

    # 1. sexy / japanese
    for w in _NG_SEXY_JP:
        if w in text_lower:
            return f"NGワード({w})"

    # 2. ありがとう
    if "ありがとう" in text:
        return "NGワード(ありがとう)"

    # 3. メッセージ
    if "メッセージ" in text:
        return "NGワード(メッセージ)"

    # 4. 113-word adult/livestream/promotion bulk
    for w in _NG_ADULT_BULK:
        if w.lower() in text:
            return f"NGワード({w})"

    # 5. エロ系 5 words
    for w in _NG_ERO_GROUP:
        if w.lower() in text:
            return f"NGワード({w})"

    # 6. 推し
    if "推し" in text:
        return "NGワード(推し)"

    # 7. video-sale group(lower)
    for w in _NG_VIDEO_SALE_GROUP:
        if w.lower() in text_lower:
            return f"NGワード({w})"

    # 8. word-boundary matches for short ASCII tokens
    for w in _NG_WORD_BOUNDARY:
        if re.search(rf"(?<![a-z0-9_]){re.escape(w)}(?![a-z0-9_])", text_lower):
            return f"NGワード({w})"

    # 9. nidone / 歓迎 / 孤独
    for w in _NG_NIDONE_GROUP:
        if w.lower() in text:
            return f"NGワード({w})"

    return None
