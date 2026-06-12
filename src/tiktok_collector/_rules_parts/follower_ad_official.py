"""フォロワー上限超過 + 広告系 + 公式/法人系 — 3 サブチェック。

  1. follower_count > rules.max_followers → 「フォロワー数NG({count})」
  2. text に広告系 24 語 + rules.ad_keywords → 「広告/PR」
  3. text に公式/法人系 80+ 語 + rules.official_keywords → 「公式/企業系({hit})」
"""
from __future__ import annotations


from ._helpers import _get, _contains_any, _load_extra_words


_AD_WORDS: list[str] = [
    "広告", "promotion", "promoted", "sponsored", "スポンサー", "提供", "案件",
    "タイアップ", "企業案件", "#ad", "#pr", "paid partnership", "shop now",
    "購入はこちら", "詳細はこちら", "キャンペーン", "無料体験", "資料請求",
    "セール", "割引", "クーポン", "予約受付", "販売中",
]

_OFFICIAL_WORDS: list[str] = [
    "公式", "official", "_official", ".official", "official_jp", "japan.official",
    "認証", "verify", "verified", "bluecheck", "blue check",
    "企業", "会社", "株式会社", "有限会社", "合同会社",
    "company", "corporation", "holdings", "ホールディングス",
    "brand", "ブランド", "shop", "store", "ecサイト", "通販", "online store", "オンラインストア",
    "news", "media", "press", "magazine", "編集部", "新聞", "テレビ", "番組", "放送",
    "事務局", "広報", "採用", "求人", "recruit", "career",
    "clinic", "クリニック", "美容外科", "美容皮膚科", "サロン", "美容室", "整体", "整骨院",
    "school", "スクール", "academy", "アカデミー", "studio", "スタジオ",
    "不動産", "賃貸", "物件", "住宅", "ハウス", "建築", "施工", "工務店",
    "カードローン", "cardloan", "loan", "保険", "金融", "投資スクール",
    "ホテル", "旅館", "観光協会", "旅行会社", "ガイド", "guide",
    "協会", "団体", "連盟", "法人", "プロジェクト",
    "selectshop", "select shop", "apparel shop", "アパレルショップ", "セレクトショップ",
    "イオンモール", "ショッピングモール", "店舗", "販売店", "新作入荷",
    "visa",
    "adobefirefly",
    "adobepartner",
    "リクルート",
]


def check(text: str, candidate, rules) -> str | None:
    # 1. フォロワー上限
    max_followers = _get(rules, "max_followers", 2000)
    try:
        max_followers = int(max_followers)
    except Exception:
        max_followers = 2000
    follower_count = _get(candidate, "follower_count", None)
    if follower_count not in (None, ""):
        try:
            if int(follower_count) > max_followers:
                return f"フォロワー数NG({int(follower_count)})"
        except Exception:
            pass

    # 2. 広告/PR
    hit = _contains_any(text, _AD_WORDS + _load_extra_words(rules, "ad_keywords"))
    if hit:
        return "広告/PR"

    # 3. 公式/法人系
    hit = _contains_any(text, _OFFICIAL_WORDS + _load_extra_words(rules, "official_keywords"))
    if hit:
        return "公式/企業系(" + hit + ")"

    return None
