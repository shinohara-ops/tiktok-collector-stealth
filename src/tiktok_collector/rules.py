
from __future__ import annotations

import re
from typing import Callable, Optional

from ._rules_parts import similar_excluded as _similar_excluded
from ._rules_parts import underage_pair as _underage_pair
from ._rules_parts import mass_produced as _mass_produced
from ._rules_parts import underage_school_age as _underage_school_age
from ._rules_parts import colored_excluded_ids as _colored_excluded_ids
from ._rules_parts import underage_tail_id as _underage_tail_id
from ._rules_parts import underage_v2_band as _underage_v2_band
from ._rules_parts import ng_no_bio_yet as _ng_no_bio_yet
from ._rules_parts import colored_leak_v2 as _colored_leak_v2
from ._rules_parts import foreign_account as _foreign_account
from ._rules_parts import noise_idol_music as _noise_idol_music
from ._rules_parts import vn_affiliate_insta as _vn_affiliate_insta
from ._rules_parts import indonesian_malay as _indonesian_malay
from ._rules_parts import stream_hashtag as _stream_hashtag
from ._rules_parts import non_jp_script_emoji_bio as _non_jp_script_emoji_bio
from ._rules_parts import similar_v1 as _similar_v1
from ._rules_parts import colored_leak_v2_words as _colored_leak_v2_words
from ._rules_parts import colored_leak_v1_words as _colored_leak_v1_words
from ._rules_parts import v5_foreign as _v5_foreign
from ._rules_parts import extra_ng_1 as _extra_ng_1
from ._rules_parts import foreign_vn_redux as _foreign_vn_redux
from ._rules_parts import extra_ng_2 as _extra_ng_2
from ._rules_parts import account_meta_basic as _account_meta_basic
from ._rules_parts import follower_ad_official as _follower_ad_official
from ._rules_parts import age_foreign_agency as _age_foreign_agency
from ._rules_parts import category_keywords as _category_keywords
from ._rules_parts import v5_final_combos as _v5_final_combos


# Sheets「NGワード」タブからカテゴリ別 NG ワードを供給するためのフック。
# main.py 起動時に set_ng_keyword_provider() で登録する。未登録なら従来通り
# config.yaml と固定リストのみで動作。
_ng_keyword_provider: Optional[Callable[[str], list[str]]] = None

# Sheets の「適用範囲」「Bio空必須」列を活かしたメタ付き判定用フック。
# 各エントリは {"word": str, "scope": "all"|"hashtag"|"bio",
#               "bio_empty_required": bool, "category": str}
_ng_keyword_meta_provider: Optional[Callable[[str], list[dict]]] = None


def set_ng_keyword_provider(provider: Optional[Callable[[str], list[str]]]) -> None:
    global _ng_keyword_provider
    _ng_keyword_provider = provider


def set_ng_keyword_meta_provider(provider: Optional[Callable[[str], list[dict]]]) -> None:
    """Sheets 由来のメタ付き NG ワード(scope / bio_empty_required)を供給するフック。
    set_ng_keyword_provider と独立で、両方登録できる。未登録なら scoped 判定は無効。"""
    global _ng_keyword_meta_provider
    _ng_keyword_meta_provider = provider


def _check_scoped_ng_words(candidate, category: str) -> Optional[str]:
    """Sheets メタプロバイダから category のワードリストを引き、scope/bio_empty_required を満たすかチェック。
    最初にヒットしたものを reason 文字列にして返す。何も該当しなければ None。

    - scope=all      : 既存の get_ng_keywords と同じ広い text に部分一致(_load_extra_words 経路で
                       すでに評価されているケースが多いので、ここでは noop 扱いにしない=重複検査は
                       許容する。誤検知より取りこぼし防止)。
    - scope=hashtag  : ハッシュタグだけに部分一致。
    - scope=bio      : Bio(signature / bio / profile_bio)だけに部分一致。
    - bio_empty_required=True : 上記に加えて Bio が完全に空のときだけ NG とする。
    """
    if _ng_keyword_meta_provider is None:
        return None
    try:
        entries = _ng_keyword_meta_provider(category) or []
    except Exception:
        return None
    if not entries:
        return None

    hashtags_raw = _get(candidate, "hashtags", "") or ""
    if isinstance(hashtags_raw, (list, tuple, set)):
        hashtags_text = " ".join(str(x) for x in hashtags_raw)
    else:
        hashtags_text = str(hashtags_raw or "")
    hashtags_lower = hashtags_text.lower()

    bio_text = str(
        _get(candidate, "signature", "")
        or _get(candidate, "bio", "")
        or _get(candidate, "profile_bio", "")
        or _get(candidate, "profile_text", "")
        or ""
    )
    bio_lower = bio_text.lower()
    bio_is_empty = bio_text.strip() == ""

    full_text = _candidate_text(candidate)  # 既に lower 済み

    for entry in entries:
        if not isinstance(entry, dict):
            continue
        word = str(entry.get("word", "") or "").strip()
        if not word:
            continue
        if entry.get("bio_empty_required") and not bio_is_empty:
            continue
        scope = str(entry.get("scope", "all") or "all").lower()
        word_l = word.lower()
        hit = False
        if scope == "hashtag":
            hit = word_l in hashtags_lower
        elif scope == "bio":
            hit = word_l in bio_lower
        else:  # all
            hit = word_l in full_text
        if hit:
            return f"NGワード({word})"
    return None


def _get(obj, name, default=None):
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _norm(s) -> str:
    if s is None:
        return ""
    return str(s).lower().replace("\u3000", " ").strip()


def _candidate_text(candidate) -> str:
    parts = [
        _get(candidate, "unique_id", ""),
        _get(candidate, "display_name", ""),
        _get(candidate, "profile_url", ""),
        _get(candidate, "post_url", ""),
        _get(candidate, "hashtags", ""),
        _get(candidate, "signature", ""),
        _get(candidate, "caption", ""),
        _get(candidate, "description", ""),
        _get(candidate, "bio", ""),
    ]
    return _norm(" ".join([str(x) for x in parts if x]))




    # 低優先度除外: ハッシュタグにfypという文字列があり、かつプロフィール紹介文が空欄の場合のみ除外
    try:
        _profile_bio = (
            _get(candidate, "profile_bio", None)
            or _get(candidate, "bio", None)
            or _get(candidate, "signature", None)
            or _get(candidate, "profile_text", None)
            or _get(candidate, "description", None)
            or _get(candidate, "desc", None)
            or ""
        )
        _hashtags_raw = (
            _get(candidate, "hashtags", None)
            or _get(candidate, "hashtag", None)
            or _get(candidate, "tags", None)
            or _get(candidate, "tag_text", None)
            or _get(candidate, "hashtag_text", None)
            or ""
        )
    except Exception:
        _profile_bio = (
            getattr(candidate, "profile_bio", None)
            or getattr(candidate, "bio", None)
            or getattr(candidate, "signature", None)
            or getattr(candidate, "profile_text", None)
            or getattr(candidate, "description", None)
            or getattr(candidate, "desc", None)
            or ""
        )
        _hashtags_raw = (
            getattr(candidate, "hashtags", None)
            or getattr(candidate, "hashtag", None)
            or getattr(candidate, "tags", None)
            or getattr(candidate, "tag_text", None)
            or getattr(candidate, "hashtag_text", None)
            or ""
        )
    if isinstance(_hashtags_raw, (list, tuple, set)):
        _hashtags_text = " ".join([str(x) for x in _hashtags_raw]).lower()
    else:
        _hashtags_text = str(_hashtags_raw).lower()
    if str(_profile_bio).strip() == "" and "fyp" in _hashtags_text:
        return "プロフィール紹介文空欄(fyp)"
def _contains_any(text: str, words) -> str:
    for w in words:
        if not w:
            continue
        ww = _norm(w)
        if not ww:
            continue

        # 短い英字だけのワードは部分一致させない
        # 例: inc/ad/pr/tv が通常IDや英単語の一部で誤爆するのを防ぐ
        if re.fullmatch(r"[a-z0-9]{1,4}", ww):
            if re.search(rf"(?<![a-z0-9]){re.escape(ww)}(?![a-z0-9])", text):
                return str(w)
            continue

        if ww in text:
            return str(w)
    return ""


def _load_extra_words(rules, key):
    value = _get(rules, key, [])
    if value is None:
        yaml_words: list = []
    elif isinstance(value, str):
        yaml_words = [x.strip() for x in re.split(r"[,、\n]", value) if x.strip()]
    elif isinstance(value, (list, tuple, set)):
        yaml_words = list(value)
    else:
        yaml_words = []

    # Sheets「NGワード」タブから来る分をマージする。プロバイダ未登録/読込失敗時は空。
    sheet_words: list = []
    if _ng_keyword_provider is not None:
        try:
            # rules.py 内の呼び出しは "ad_keywords" / "ng_keywords" 等のサフィックス付き。
            # Sheets のカテゴリ列はサフィックス無し("ad" / "general" 等)で運用するため、
            # キーから _keywords を剥がしてからプロバイダに問い合わせる。
            short_key = key[:-9] if key.endswith("_keywords") else key
            sheet_words = list(_ng_keyword_provider(short_key) or [])
            # "ng" は意味的に rules.py の general_words と同じバケットなので、
            # シート側で "general" と書かれていた場合も拾えるよう二重に問い合わせる。
            if short_key == "ng":
                sheet_words = sheet_words + list(_ng_keyword_provider("general") or [])
        except Exception:
            sheet_words = []

    return yaml_words + sheet_words


def _foreign_score(text: str) -> int:
    # 日本語の漢字は除外。ハングル/タイ語/ロシア語/ネパール語/クメール語/アラビア語などを検出
    patterns = [
        r"[\uac00-\ud7af]",          # Hangul
        r"[\u0e00-\u0e7f]",          # Thai
        r"[\u0400-\u04ff]",          # Cyrillic
        r"[\u0900-\u097f]",          # Devanagari
        r"[\u1780-\u17ff]",          # Khmer
        r"[\u0600-\u06ff]",          # Arabic
    ]
    return sum(len(re.findall(p, text)) for p in patterns)


def _looks_like_foreign(text: str) -> bool:
    if _foreign_score(text) >= 4:
        return True
    flags = ["🇰🇷", "🇨🇳", "🇹🇭", "🇻🇳", "🇷🇺", "🇳🇵", "🇰🇭", "🇮🇩", "🇵🇭", "🇮🇳"]
    if any(f in text for f in flags):
        return True
    words = [
        "korea", "korean", "china", "chinese", "thai", "thailand", "vietnam", "vietnamese",
        "russia", "russian", "nepal", "nepali", "khmer", "indonesia", "philippines",
    ]
    return any(w in text for w in words)


def _age_ng(text: str) -> str:
    patterns = [
        "#08", "#09", "#10", "#11", "#12", "#13", "#14", "#15",
        "08line", "09line", "10line", "11line", "12line", "13line", "14line", "15line",
        "fjk", "sjk", "ljk", "jk", "jc", "js",
        "高校生", "中学生", "受験生", "通信制高校",
        "17歳", "16歳", "15歳", "14歳", "13歳",
        "2008", "2009", "2010", "2011", "2012",
        "中一",
        "中二",
        "中三",
        "中1",
        "中2",
        "中3",
        "中学一年",
        "中学二年",
        "中学三年",
        "中学1年",
        "中学2年",
        "中学3年",
        "中学1年生",
        "中学2年生",
        "中学3年生",
    ]
    hit = _contains_any(text, patterns)
    if hit:
        return "年齢NG(" + hit + ")"
    return ""


def _verified_flag(candidate) -> bool:
    for key in ["is_verified", "verified", "is_blue_verified", "blue_check", "has_blue_check", "is_certified"]:
        try:
            if bool(_get(candidate, key, False)):
                return True
        except Exception:
            pass
    return False


def local_skip_reason(candidate, rules=None) -> str | None:
    text = _candidate_text(candidate)

    # 追加除外: 2764色付き行の類似アカウント汎用除外
    try:
        _cs_uid = (
            _get(candidate, "unique_id", None)
            or _get(candidate, "user_id", None)
            or _get(candidate, "id", None)
            or ""
        )
        _cs_name = (
            _get(candidate, "display_name", None)
            or _get(candidate, "nickname", None)
            or _get(candidate, "name", None)
            or ""
        )
        _cs_bio = (
            _get(candidate, "profile_bio", None)
            or _get(candidate, "bio", None)
            or _get(candidate, "signature", None)
            or _get(candidate, "profile_text", None)
            or _get(candidate, "description", None)
            or _get(candidate, "desc", None)
            or ""
        )
        _cs_tags_raw = (
            _get(candidate, "hashtags", None)
            or _get(candidate, "hashtag", None)
            or _get(candidate, "tags", None)
            or _get(candidate, "tag_text", None)
            or _get(candidate, "hashtag_text", None)
            or ""
        )
    except Exception:
        _cs_uid = getattr(candidate, "unique_id", None) or getattr(candidate, "user_id", None) or getattr(candidate, "id", None) or ""
        _cs_name = getattr(candidate, "display_name", None) or getattr(candidate, "nickname", None) or getattr(candidate, "name", None) or ""
        _cs_bio = getattr(candidate, "profile_bio", None) or getattr(candidate, "bio", None) or getattr(candidate, "signature", None) or getattr(candidate, "profile_text", None) or getattr(candidate, "description", None) or getattr(candidate, "desc", None) or ""
        _cs_tags_raw = getattr(candidate, "hashtags", None) or getattr(candidate, "hashtag", None) or getattr(candidate, "tags", None) or getattr(candidate, "tag_text", None) or getattr(candidate, "hashtag_text", None) or ""

    if isinstance(_cs_tags_raw, (list, tuple, set)):
        _cs_tags = " ".join([str(x) for x in _cs_tags_raw]).strip()
    else:
        _cs_tags = str(_cs_tags_raw or "").strip()

    _cs_uid_s = str(_cs_uid or "").strip().replace("@", "")
    _cs_name_s = str(_cs_name or "").strip()
    _cs_bio_s = str(_cs_bio or "").strip()
    _cs_full = " ".join([_cs_uid_s, _cs_name_s, _cs_tags, _cs_bio_s])
    _cs_low = _cs_full.lower()
    _cs_digit_text = _cs_full.translate(str.maketrans("０１２３４５６７８９", "0123456789"))

    _cs_bio_without_symbols = re.sub(r"[\W_\s]+", "", _cs_bio_s, flags=re.UNICODE)
    _cs_bio_empty_or_emoji = (_cs_bio_s == "") or (len(_cs_bio_without_symbols) == 0) or (len(_cs_bio_s) <= 2)


    # ────────────────────────────────────────────────────────────────
    # SECTION: 類似アカウントの hardcoded ワード(テンプレ/音楽系)
    # → src/tiktok_collector/_rules_parts/similar_excluded.py に抽出済
    # ────────────────────────────────────────────────────────────────
    if (r := _similar_excluded.check(_cs_low)) is not None:
        return r


    # ────────────────────────────────────────────────────────────────
    # SECTION: 未成年系 — 08/09 ペア表記の判定
    # → src/tiktok_collector/_rules_parts/underage_pair.py に抽出済
    # ────────────────────────────────────────────────────────────────
    if (r := _underage_pair.check(_cs_digit_text)) is not None:
        return r


    # ────────────────────────────────────────────────────────────────
    # SECTION: 量産系 — ノイズタグ多数 + Bio 同一/空
    # → src/tiktok_collector/_rules_parts/mass_produced.py に抽出済
    # ────────────────────────────────────────────────────────────────
    if (r := _mass_produced.check(_cs_low, _cs_uid_s, _cs_bio_empty_or_emoji, _cs_tags, _cs_bio_s)) is not None:
        return r


    # 追加NG: 学校行事・学年・未成年年齢表記

    # ────────────────────────────────────────────────────────────────
    # SECTION: 未成年系 — 学校行事/学年/年齢正規表現
    # → src/tiktok_collector/_rules_parts/underage_school_age.py に抽出済
    # ────────────────────────────────────────────────────────────────
    if (r := _underage_school_age.check(text)) is not None:
        return r


    # 2764行目以降の色付きアカウントID除外

    # ────────────────────────────────────────────────────────────────
    # SECTION: 色付き除外 ID 群(2764 行スナップショット)
    # → src/tiktok_collector/_rules_parts/colored_excluded_ids.py に抽出済
    # ────────────────────────────────────────────────────────────────
    if (r := _colored_excluded_ids.check_2764(_cs_uid_s)) is not None:
        return r


    # ────────────────────────────────────────────────────────────────
    # SECTION: 未成年系 — 08/09 末尾ID + 絵文字 Bio + テンプレ歌
    # → src/tiktok_collector/_rules_parts/underage_tail_id.py に抽出済
    # ────────────────────────────────────────────────────────────────
    if (r := _underage_tail_id.check(_cs_uid_s, _cs_name_s, _cs_bio_s, _cs_tags)) is not None:
        return r



    # ────────────────────────────────────────────────────────────────
    # SECTION: 未成年系 — 09-08 ペア / シャドバン / CapCut
    # → src/tiktok_collector/_rules_parts/underage_v2_band.py に抽出済
    # ────────────────────────────────────────────────────────────────
    if (r := _underage_v2_band.check(_cs_uid_s, _cs_name_s, _cs_bio_s, _cs_tags)) is not None:
        return r


    # 追加NGワード: No bio yet

    # ────────────────────────────────────────────────────────────────
    # SECTION: NGワード — "No bio yet"
    # → src/tiktok_collector/_rules_parts/ng_no_bio_yet.py に抽出済
    # ────────────────────────────────────────────────────────────────
    if (r := _ng_no_bio_yet.check(text)) is not None:
        return r



    # ────────────────────────────────────────────────────────────────
    # SECTION: 色付き除外 ID 群(1650 行スナップショット)
    # → src/tiktok_collector/_rules_parts/colored_excluded_ids.py の check_1650
    # ────────────────────────────────────────────────────────────────
    if (r := _colored_excluded_ids.check_1650(_cs_uid_s)) is not None:
        return r



    # ────────────────────────────────────────────────────────────────
    # SECTION: 汎用 色付き除外 v2(リンク/未成年/外国語/ランダムID/fyp/中文/反復ASCII)
    # → src/tiktok_collector/_rules_parts/colored_leak_v2.py に抽出済
    # ────────────────────────────────────────────────────────────────
    if (r := _colored_leak_v2.check(_cs_uid_s, _cs_name_s, _cs_bio_s, _cs_tags)) is not None:
        return r



    # ────────────────────────────────────────────────────────────────
    # SECTION: 外国語/海外アカウント — ベトナム/中文/韓国語/英文
    # → src/tiktok_collector/_rules_parts/foreign_account.py に抽出済
    # ────────────────────────────────────────────────────────────────
    if (r := _foreign_account.check(_cs_uid_s, _cs_name_s, _cs_bio_s, _cs_tags)) is not None:
        return r



    # ────────────────────────────────────────────────────────────────
    # SECTION: ノイズ/アイドル/音楽系タグ(daun muda / onephony / 反復ASCII)
    # → src/tiktok_collector/_rules_parts/noise_idol_music.py に抽出済
    # ────────────────────────────────────────────────────────────────
    if (r := _noise_idol_music.check(_cs_uid_s, _cs_name_s, _cs_bio_s, _cs_tags)) is not None:
        return r



    # ────────────────────────────────────────────────────────────────
    # SECTION: ベトナム/affiliate/Instagram/メンションのみ Bio + K-POP タグ
    # → src/tiktok_collector/_rules_parts/vn_affiliate_insta.py に抽出済
    # ────────────────────────────────────────────────────────────────
    if (r := _vn_affiliate_insta.check(_cs_uid_s, _cs_name_s, _cs_bio_s, _cs_tags)) is not None:
        return r



    # ────────────────────────────────────────────────────────────────
    # SECTION: インドネシア語/マレー語系タグワード
    # → src/tiktok_collector/_rules_parts/indonesian_malay.py に抽出済
    # ────────────────────────────────────────────────────────────────
    if (r := _indonesian_malay.check(_cs_uid_s, _cs_name_s, _cs_bio_s, _cs_tags)) is not None:
        return r



    # ────────────────────────────────────────────────────────────────
    # SECTION: ライブ配信/08/09 ハッシュタグトークン
    # → src/tiktok_collector/_rules_parts/stream_hashtag.py に抽出済
    # ────────────────────────────────────────────────────────────────
    if (r := _stream_hashtag.check(_cs_uid_s, _cs_name_s, _cs_bio_s, _cs_tags)) is not None:
        return r



    # ────────────────────────────────────────────────────────────────
    # SECTION: 非日本語スクリプト + 絵文字のみ Bio + ASCII タグ
    # → src/tiktok_collector/_rules_parts/non_jp_script_emoji_bio.py に抽出済
    # ────────────────────────────────────────────────────────────────
    if (r := _non_jp_script_emoji_bio.check(_cs_uid_s, _cs_name_s, _cs_bio_s, _cs_tags)) is not None:
        return r



    # ────────────────────────────────────────────────────────────────
    # SECTION: 類似アカウント v1(外部リンク/アダルト/コスプレ/空 Bio + ASCII タグ/ランダム ID)
    # → src/tiktok_collector/_rules_parts/similar_v1.py に抽出済
    # ────────────────────────────────────────────────────────────────
    if (r := _similar_v1.check(_cs_uid_s, _cs_name_s, _cs_bio_s, _cs_tags)) is not None:
        return r



    # ────────────────────────────────────────────────────────────────
    # SECTION: 色付き除外 ID 群(1539 行スナップショット)
    # → src/tiktok_collector/_rules_parts/colored_excluded_ids.py の check_1539
    # ────────────────────────────────────────────────────────────────
    if (r := _colored_excluded_ids.check_1539(_cs_uid_s)) is not None:
        return r



    # ────────────────────────────────────────────────────────────────
    # SECTION: 色付き漏れ v2 — ワードリスト + タグコンボ
    # → src/tiktok_collector/_rules_parts/colored_leak_v2_words.py に抽出済
    # ────────────────────────────────────────────────────────────────
    if (r := _colored_leak_v2_words.check(text, _cs_bio_s, _cs_tags)) is not None:
        return r

    # Sheets 由来のメタ付き NG ワード(scope=hashtag/bio/all + bio_empty_required)。
    # Sheets が空ならここは何もしない=既存ハードコード判定の挙動と完全一致。
    _scoped_hit = _check_scoped_ng_words(candidate, "general")
    if _scoped_hit:
        return _scoped_hit



    # ────────────────────────────────────────────────────────────────
    # SECTION: 色付き漏れ v1 — ワードリスト + タグコンボ(v2 と部分重複)
    # → src/tiktok_collector/_rules_parts/colored_leak_v1_words.py に抽出済
    # ────────────────────────────────────────────────────────────────
    if (r := _colored_leak_v1_words.check(text, _cs_bio_s, _cs_tags)) is not None:
        return r



    # ────────────────────────────────────────────────────────────────
    # SECTION: v5 外国語キーワード + 中文スパム + ベトナム発音記号 + 繁体字
    # → src/tiktok_collector/_rules_parts/v5_foreign.py に抽出済
    # ────────────────────────────────────────────────────────────────
    if (r := _v5_foreign.check(text)) is not None:
        return r



    # ────────────────────────────────────────────────────────────────
    # SECTION: 追加 NG ワード 1(teamwork/ダンス/推し/アダルト/ファッション)
    # → src/tiktok_collector/_rules_parts/extra_ng_1.py に抽出済
    # ────────────────────────────────────────────────────────────────
    if (r := _extra_ng_1.check(text, _cs_tags)) is not None:
        return r


    # ────────────────────────────────────────────────────────────────
    # SECTION: 外国語/ベトナム語キーワードリスト + 中文スパム(再掲)
    # → src/tiktok_collector/_rules_parts/foreign_vn_redux.py に抽出済
    # ────────────────────────────────────────────────────────────────
    if (r := _foreign_vn_redux.check(text)) is not None:
        return r


    # ────────────────────────────────────────────────────────────────
    # SECTION: 追加 NG ワード 2(sexy/感謝/メンションスパム/推し/bot/nidone)
    # → src/tiktok_collector/_rules_parts/extra_ng_2.py に抽出済
    # ────────────────────────────────────────────────────────────────
    if (r := _extra_ng_2.check(text)) is not None:
        return r


    # ────────────────────────────────────────────────────────────────
    # SECTION: フォロワー数チェック + AI 生成 ID 形式 + メタフラグ
    # → src/tiktok_collector/_rules_parts/account_meta_basic.py に抽出済
    # ────────────────────────────────────────────────────────────────
    if (r := _account_meta_basic.check(candidate, _verified_flag, _get, _norm)) is not None:
        return r


    # ────────────────────────────────────────────────────────────────
    # SECTION: フォロワー上限超過 + 広告/PR + 公式/法人系
    # → src/tiktok_collector/_rules_parts/follower_ad_official.py に抽出済
    # ────────────────────────────────────────────────────────────────
    if (r := _follower_ad_official.check(text, candidate, rules, _get, _contains_any, _load_extra_words)) is not None:
        return r


    # ────────────────────────────────────────────────────────────────
    # SECTION: 年齢 + 外国語 + 事務所系
    # → src/tiktok_collector/_rules_parts/age_foreign_agency.py に抽出済
    # ────────────────────────────────────────────────────────────────
    if (r := _age_foreign_agency.check(text, rules, _age_ng, _looks_like_foreign, _contains_any, _load_extra_words)) is not None:
        return r


    # ────────────────────────────────────────────────────────────────
    # SECTION: Live / Music(2000+ アーティスト) / Game / Pet / Food / general NG
    # → src/tiktok_collector/_rules_parts/category_keywords.py に抽出済
    # ────────────────────────────────────────────────────────────────
    if (r := _category_keywords.check(text, rules, _contains_any, _load_extra_words)) is not None:
        return r


    # ────────────────────────────────────────────────────────────────
    # SECTION: v5 ハッシュコンボ + 数字のみタグ + 空 Bio/タグ
    # → src/tiktok_collector/_rules_parts/v5_final_combos.py に抽出済
    # ────────────────────────────────────────────────────────────────
    if (r := _v5_final_combos.check(_cs_bio_s, _cs_tags)) is not None:
        return r

    # ────────────────────────────────────────────────────────────────
    # SECTION: 全てパスした → return None
    # ────────────────────────────────────────────────────────────────
    return None


def detect_blackband(image_path: str, top_bottom_dark_ratio_threshold: float = 0.72, dark_pixel_threshold: int = 35) -> bool:
    try:
        from PIL import Image
        img = Image.open(image_path).convert("RGB")
        w, h = img.size
        if w <= 0 or h <= 0:
            return False

        band_h = max(1, int(h * 0.12))
        top = img.crop((0, 0, w, band_h))
        bottom = img.crop((0, h - band_h, w, h))

        def dark_ratio(crop):
            pixels = list(crop.getdata())
            if not pixels:
                return 0.0
            dark = 0
            for r, g, b in pixels:
                if (r + g + b) / 3 <= dark_pixel_threshold:
                    dark += 1
            return dark / len(pixels)

        return dark_ratio(top) >= top_bottom_dark_ratio_threshold and dark_ratio(bottom) >= top_bottom_dark_ratio_threshold
    except Exception:
        return False
