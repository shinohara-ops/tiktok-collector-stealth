"""NGワード — "No bio yet"。

TikTok の新規アカウントで Bio が未設定だと、英語ロケールでは "No bio yet"
というプレースホルダ文字列が表示される。これがそのまま candidate のテキスト
(uid/name/tags/bio を結合した text)に入っていれば、bio 未記入の海外アカウント
としてマークして除外する。

入力: text — _candidate_text(candidate) の結果。lower 化は内部で行う。
"""
from __future__ import annotations


def check(text: str) -> str | None:
    if "no bio yet" in text.lower():
        return "NGワード(No bio yet)"
    return None
