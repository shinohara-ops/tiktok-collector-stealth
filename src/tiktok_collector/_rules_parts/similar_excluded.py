"""類似アカウントの hardcoded ワード判定。

過去に大量採用された「テンプレお借りしました」「シャドバン」「黒毛和牛上塩タン焼680円」
などのフレーズが含まれているアカウントを除外する。これらは特定の流行・テンプレ系
コンテンツや類似アカウント群の識別用で、bio / hashtag / display_name / unique_id の
どこに含まれていても発火する。

判定対象: candidate のテキスト全体を結合し lower 化した文字列(_cs_low)。
"""
from __future__ import annotations

# 過去採用群から逆引きで特定された「類似アカウントの目印フレーズ」
_SIMILAR_EXCLUDED_WORDS: list[str] = [
    "テンプレートお借りしました",
    "テンプレお借りしました",
    "お借りしました",
    "この歌好き",
    "この音源好き",
    "音源好き",
    "黒毛和牛上塩タン焼680円",
    "黒毛和牛上塩タン焼",
    "シャドバン",
    "シャドウバン",
    "シャドバン解除",
    "げろげろぴー",
    "unsunghero",
    "runaar",
    "村谷はるな",
    "はるち",
]


def check(text_lower: str) -> str | None:
    """類似除外ワードのいずれかが text_lower に含まれていれば
    f"類似除外({word})" を返す。何もマッチしなければ None。"""
    for w in _SIMILAR_EXCLUDED_WORDS:
        ws = str(w or "").strip()
        if ws and ws.lower() in text_lower:
            return f"類似除外({ws})"
    return None
