"""アカウントメタの基本判定 — フォロワー数取得 + AI ID 形式 + メタフラグ。

6 サブチェック:
  1. follower_count が None/空 → 「フォロワー数未取得」(runner 側でリロード合図)
  2. unique_id の正規化形が "ai_/ai-/_ai/-ai" を含む → 「AI生成系ID(ai区切り)」
  3. unique_id が "user" で始まる → 「ID形式NG(user始まり)」
  4. is_following=True → 「フォロー中」
  5. is_ad=True → 「広告/PR」
  6. _verified_flag(candidate)=True → 「認証/青チェック」
"""
from __future__ import annotations

import re

from ._helpers import _get, _norm, _verified_flag


_AI_DELIM_PATTERN = re.compile(r"(^ai[_-]|[_-]ai($|[_-]))")


def check(candidate) -> str | None:
    # 1. follower_count 取得チェック
    try:
        fc_required = _get(candidate, "follower_count", "")
    except Exception:
        fc_required = getattr(candidate, "follower_count", "")
    if fc_required is None or str(fc_required).strip() == "":
        return "フォロワー数未取得"

    # 2. AI 生成 ID 形式
    try:
        uid_for_ai = _norm(_get(candidate, "unique_id", ""))
    except Exception:
        uid_for_ai = str(getattr(candidate, "unique_id", "") or "").lower()
    if _AI_DELIM_PATTERN.search(uid_for_ai):
        return "AI生成系ID(ai区切り)"

    # 3. user 接頭辞
    uid = _norm(_get(candidate, "unique_id", ""))
    if uid.startswith("user"):
        return "ID形式NG(user始まり)"

    # 4. フォロー中
    if bool(_get(candidate, "is_following", False)):
        return "フォロー中"

    # 5. 広告フラグ
    if bool(_get(candidate, "is_ad", False)):
        return "広告/PR"

    # 6. 認証バッジ
    if _verified_flag(candidate):
        return "認証/青チェック"

    return None
