"""追加 NG ワード 1 — teamwork / ダンス / 推し / アダルト / ファッション系。

複数の return が縦に並ぶ追加 NG ブロックを 1 関数にまとめる。判定順は厳守。

  1. text に "teamwork" を含む → 「NGワード(teamwork)」
  2. 「踊る」「極愛パラドックス」「ラブパラ」「大人ガーリー」「アラフィフ」
     のいずれかが text に含まれる → 「NGワード({word})」
  3. ハッシュタグに「美人」「モデル」「かわいい」が全部含まれる
     → 「ハッシュタグNG(美人/モデル/かわいい)」
  4. 「男の娘」「偽娘」「女装男子」「ニューハーフ」のいずれか → 「NGワード({word})」
  5. 「サブスク」「彼氏募集」「彼氏募集中」のいずれか → 「NGワード({word})」
  6. lower で「followme」「follow me」のいずれか → 「NGワード({word})」
  7. lower で「fypシ」「foryou」「4u」「yah」のいずれか → 「NGワード({word})」
  8. 「料理動画」「料理」のいずれか → 「NGワード({word})」

入力:
  text — _candidate_text(candidate) の結果
  tags — _cs_tags(ハッシュタグ判定用)
"""
from __future__ import annotations


_EXTRA_NG_GROUP1: list[str] = ["踊る", "極愛パラドックス", "ラブパラ", "大人ガーリー", "アラフィフ"]
_HASHTAG_TRIPLE: list[str] = ["美人", "モデル", "かわいい"]
_EXTRA_NG_GENDER: list[str] = ["男の娘", "偽娘", "女装男子", "ニューハーフ"]
_EXTRA_NG_SUBSCRIBE: list[str] = ["サブスク", "彼氏募集", "彼氏募集中"]
_EXTRA_NG_FOLLOWME: list[str] = ["followme", "follow me"]
_EXTRA_NG_FYP_GROUP: list[str] = ["fypシ", "foryou", "4u", "yah"]
_EXTRA_NG_COOK: list[str] = ["料理動画", "料理"]


def check(text: str, tags: str) -> str | None:
    text_lower = text.lower()

    # 1. teamwork
    if "teamwork" in text_lower:
        return "NGワード(teamwork)"

    # 2. ダンス/曲/年代系
    for w in _EXTRA_NG_GROUP1:
        if w in text:
            return f"NGワード({w})"

    # 3. ハッシュタグ 3 点セット
    if all(kw in tags for kw in _HASHTAG_TRIPLE):
        return "ハッシュタグNG(美人/モデル/かわいい)"

    # 4. 女装系
    for w in _EXTRA_NG_GENDER:
        if w in text:
            return f"NGワード({w})"

    # 5. サブスク / 彼氏募集
    for w in _EXTRA_NG_SUBSCRIBE:
        if w in text:
            return f"NGワード({w})"

    # 6. followme 系(case-insensitive)
    for w in _EXTRA_NG_FOLLOWME:
        if w in text_lower:
            return f"NGワード({w})"

    # 7. fypシ / foryou / 4u / yah(case-insensitive)
    for w in _EXTRA_NG_FYP_GROUP:
        if w.lower() in text_lower:
            return f"NGワード({w})"

    # 8. 料理
    for w in _EXTRA_NG_COOK:
        if w in text:
            return f"NGワード({w})"

    return None
