from __future__ import annotations

# bio または hashtags に「にほん / japan / 日本」を含むアカウントを早期 skip する。
# 海外運営の日本紹介系・日本コンテンツ転載系で頻出するシグナル。
#
# 注意: 「日本」は日本人運営の正当アカウント(「東京/日本」「日本一周」「日本語」)
# でも使われる。ユーザー指示で NG ワードに含めているが、誤発火が増えてきたら
# このリストから外す or scope を絞る判断が必要。

# 大文字小文字を区別しないで一致させるキーワード。
_JAPAN_KEYWORDS_CI: tuple[str, ...] = (
    "japan",
)
# 完全一致(部分一致)で見る日本語キーワード。
_JAPAN_KEYWORDS_EXACT: tuple[str, ...] = (
    "にほん",
    "日本",
)


def check(bio: str, tags: str) -> str | None:
    text = (bio or "") + " " + (tags or "")
    if not text.strip():
        return None
    text_lower = text.lower()
    for kw in _JAPAN_KEYWORDS_CI:
        if kw in text_lower:
            return f"NGワード({kw})"
    for kw in _JAPAN_KEYWORDS_EXACT:
        if kw in text:
            return f"NGワード({kw})"
    return None
