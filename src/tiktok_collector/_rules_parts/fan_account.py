from __future__ import annotations

# アイドル/タレント等のファン・応援アカウント。bio とタグの両方を見る。
# `推し` 単独では「推しソング」「推しメン語り」など正当アカウントもあるので、
# 「垢」「カメラ」「ゴト」「活」が後ろに付いた強いシグナルだけを拾う。
_FAN_KEYWORDS: tuple[str, ...] = (
    "ファン垢",
    "応援垢",
    "推し垢",
    "担当垢",
    "オタ垢",
    "ファンアカ",
    "応援アカウント",
    "推し活",
    "推しカメラ",
    "推しゴト",
    "推しごと",
    "ヲタ活",
    "現場垢",
    "現場担当",
)


def check(bio: str, tags: str) -> str | None:
    text = (bio or "") + " " + (tags or "")
    if not text.strip():
        return None
    for kw in _FAN_KEYWORDS:
        if kw in text:
            return f"ファン/応援アカウント({kw})"
    return None
