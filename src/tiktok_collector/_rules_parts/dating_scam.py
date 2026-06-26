"""出会い系・なりすまし・海外誘導アカウントの検出ルール。

おすすめタブに混入した2パターンを検出する:
1. テンプレBio型 — 「よかったらご連絡ください」など定型句を bio に含む
2. 中国語/海外出会い系タグ — 獨身/靚女/单身交友 など
"""
from __future__ import annotations

# Bio にこれが入っていたら出会い誘導テンプレと判定。
# 複数アカウントがほぼ同一文をコピペしていることで確認済み。
_DATING_BIO_PHRASES: tuple[str, ...] = (
    "よかったらご連絡ください",
    "よかったらメッセージください",
    "落ち着いたご縁を大切に",
    "お互いに思いやれる関係が理想",
    "焦らずゆっくり仲良く",
    "一緒にいて安心できる人と出会えたら",
    "心から大切にできる人と出会えたら",
    # 日本語なりすまし型: 不自然な「注目してください」「友達を作るのが好き」テンプレ
    "注目してください",
    "友達を作るのが好きです",
    # KakaoTalk 連絡先誘導(中国・韓国系スパムが bio に電話番号付きで記載するパターン)
    "kakaotalk",
    "カカオトーク",
)

# ハッシュタグまたは全文にこれが入っていたら出会い目的の海外アカウントと判定。
# 地理名・民族名など一般用語は除外し、出会い・マッチング文脈に固有の語のみ採用。
# (靚女/华人/马来西亚 は一般的な中国語語彙なので除外 — 海外検出は外国語スコアに委ねる)
_DATING_TAG_PHRASES: tuple[str, ...] = (
    "獨身",        # 繁体字: 独身 → シングルアピール(出会い目的)
    "单身交友",    # 簡体字: シングル出会い → 出会い目的のみの使われ方
    "有缘人",      # 中国語: 縁のある人 → 出会い/恋愛募集文脈で使われる
)


def check_bio(bio_text: str) -> str | None:
    """Bio テキストに出会い誘導の定型句が含まれていれば reason を返す。"""
    if not bio_text:
        return None
    for phrase in _DATING_BIO_PHRASES:
        if phrase in bio_text:
            return f"出会い系Bio({phrase})"
    return None


def check_tags(full_text: str) -> str | None:
    """ハッシュタグ/全文に中国語系出会い誘導ワードが含まれていれば reason を返す。"""
    if not full_text:
        return None
    for phrase in _DATING_TAG_PHRASES:
        if phrase in full_text:
            return f"海外出会い系タグ({phrase})"
    return None
