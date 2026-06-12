"""インドネシア語/マレー語系タグワード — 海外アカウント追加除外。

14 単語のハードコードリストを text 全体に部分一致でチェック。
ヒットしたら「外国語/海外({word})」。

cewek / cantik / mencari / wanita / gadis / perempuan などインドネシア語/
マレー語で日常的に使われる単語と、indonesia / jakarta / malaysia / malay
のような国名指定タグを拾う。

入力(_cs_* の strip 済み): uid_s, name_s, bio_s, tags
"""
from __future__ import annotations

_INDO_WORDS: list[str] = [
    "cewek", "cewekcantik", "cewekidaman",
    "wanita",
    "masih mencari", "cantik", "idaman", "mencari",
    "gadis", "perempuan",
    "indonesia", "jakarta",
    "malaysia", "malay",
]


def check(uid_s: str, name_s: str, bio_s: str, tags: str) -> str | None:
    full = " ".join([uid_s, name_s, tags, bio_s])
    full_lower = full.lower()
    for w in _INDO_WORDS:
        ws = str(w or "").strip()
        if ws and ws.lower() in full_lower:
            return f"外国語/海外({ws})"
    return None
