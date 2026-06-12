
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
    # ────────────────────────────────────────────────────────────────
    # 海外/ベトナム系アカウント判定強化: xuhuong / gaixinh / Vietnamese spam系
    _foreign_vn_text = text.lower()

    _foreign_vn_keywords = [
        "xuhuong", "xuhuongtiktok", "xu huong", "xuhướng", "hướng",
        "gaixinh", "gaixinhtiktok", "gai xinh", "xinhdep", "xinh dep",
        "girlxinh", "nhactrung", "dungmai", "halinh",
        "babygirl", "bikini", "binkini",
        "viral", "trending", "foryou", "hottrend",
        "follow mình", "flow em", "follow tui", "mọi người", "giúp mình",
        "lên 1000fl", "1000fl", "vào đây", "tìm gì", "em rất", "cô đơn",
        "mình", "nhé", "nhá", "đi ạ", "tui",
        "置顶找我", "gaixinhmacbinkini"
    ]

    for _kw in _foreign_vn_keywords:
        if _kw in _foreign_vn_text:
            return f"外国語/海外({_kw})"

    # ベトナム語でよく出る文字が1文字でもあれば海外扱いに寄せる
    if re.search(r"[ăâêôơưđàáạảãằắặẳẵầấậẩẫèéẹẻẽềếệểễìíịỉĩòóọỏõồốộổỗờớợởỡùúụủũừứựửữỳýỵỷỹ]", _foreign_vn_text):
        return "外国語/海外(ベトナム語文字)"

    # 中国語簡体/繁体のSNS誘導っぽい語
    _chinese_spam_keywords = [
        "置顶", "找我", "美女", "漂亮", "可爱", "关注", "私信", "主页", "點", "點擊", "點我",
        "視頻", "视频", "比基尼", "泳裝", "泳装"
    ]
    for _kw in _chinese_spam_keywords:
        if _kw in text:
            return f"外国語/海外({_kw})"



    # ────────────────────────────────────────────────────────────────
    # SECTION: 追加 NG ワード 2(sexy/感謝/メンションスパム/推し/bot/nidone)
    # ────────────────────────────────────────────────────────────────
    # 追加NGワード: sexy / Japanese
    for _extra_ng in ["sexy", "japanese"]:
        if _extra_ng in text.lower():
            return f"NGワード({_extra_ng})"


    # 追加NGワード: ありがとう
    if "ありがとう" in text:
        return "NGワード(ありがとう)"


    # 追加NGワード: メッセージ
    if "メッセージ" in text:
        return "NGワード(メッセージ)"


    # 追加NGワード一括: エロ/販売誘導/配信系（サブ垢・サブアカ除外）
    for _extra_ng in ['えち', 'えっち', 'エッチ', 'えちえち', 'エロい', 'えろい', 'エロ垢', '裏垢', '裏アカ', '裏垢女子', '裏アカ女子', '裏垢男子', 'せふれ', 'セフレ', 'オフパコ', 'ぱこ', 'パコ', 'ぬき', '抜き', '抜ける', '抜いて', 'おな', 'オナ', 'おなにー', 'オナニー', '自慰', '性欲', '欲求不満', 'むらむら', 'ムラムラ', 'むちむち', 'むち', '下ネタ', '下着', 'ランジェリー', 'パンチラ', '胸チラ', '谷間', 'おっぱい', '乳', '巨乳', '美乳', '尻', 'お尻', 'ケツ', '太もも', '脚フェチ', '動画販売', '動画売ります', '動画買って', '写真売ります', '写真販売', '個別販売', 'PayPay', 'ぺいぺい', 'ペイペイ', '貢いで', '支援して', '見せ合い', '見せて', '見たい人', '欲しい人', 'dmして', 'DMして', '秘密垢', '限定公開', '限定動画', '鍵垢', '配信者', 'ライバー', 'ライブ配信', 'LIVE配信', 'live配信', 'ファンマ', '推し活', '推して', '古参', '初見さん', '初見歓迎', 'コメントして', 'フォローして', 'フォロバ', '相互', '相互フォロー']:
        if _extra_ng.lower() in text:
            return f"NGワード({_extra_ng})"


    # 追加NGワード: エロ / おかず / えろ / エドイ / えどい
    for _extra_ng in ["エロ", "おかず", "えろ", "エドイ", "えどい"]:
        if _extra_ng.lower() in text:
            return f"NGワード({_extra_ng})"



    # 追加NGワード: 推し
    if "推し" in text:
        return "NGワード(推し)"


    # 追加NGワード: bot / 動画売る / 動画売ってます / 秘密 / jp / ライブ / live
    _extra_ng_text = text.lower()
    for _extra_ng in ["動画売る", "動画売ってます", "秘密", "ライブ"]:
        if _extra_ng.lower() in _extra_ng_text:
            return f"NGワード({_extra_ng})"
    for _extra_word_ng in ["bot", "jp", "live"]:
        if re.search(rf"(?<![a-z0-9_]){re.escape(_extra_word_ng)}(?![a-z0-9_])", _extra_ng_text):
            return f"NGワード({_extra_word_ng})"


    # 追加NGワード: にどね / ニドン / nidone / 歓迎します / 歓迎 / 孤独
    for _extra_ng in ["にどね", "ニドン", "nidone", "歓迎します", "歓迎", "孤独"]:
        if _extra_ng.lower() in text:
            return f"NGワード({_extra_ng})"



    # ────────────────────────────────────────────────────────────────
    # SECTION: フォロワー数チェック(min_followers)
    # ────────────────────────────────────────────────────────────────
    # フォロワー数が取れていない場合は、おすすめに入れない。
    # runner側でこの理由を検知したらリロードする。
    try:
        fc_required = _get(candidate, "follower_count", "")
    except Exception:
        fc_required = getattr(candidate, "follower_count", "")
    if fc_required is None or str(fc_required).strip() == "":
        return "フォロワー数未取得"


    # ────────────────────────────────────────────────────────────────
    # SECTION: AI 生成 ID 形式 + user 接頭辞 + フォロー中 + 広告フラグ + 認証バッジ
    # ────────────────────────────────────────────────────────────────

    # AI生成系ID除外: ai_ / ai- / _ai / -ai のように ai が区切り語として入るIDだけ除外
    try:
        uid_for_ai = _norm(_get(candidate, "unique_id", ""))
    except Exception:
        uid_for_ai = str(getattr(candidate, "unique_id", "") or "").lower()
    if re.search(r"(^ai[_-]|[_-]ai($|[_-]))", uid_for_ai):
        return "AI生成系ID(ai区切り)"



    uid = _norm(_get(candidate, "unique_id", ""))
    if uid.startswith("user"):
        return "ID形式NG(user始まり)"


    # フォロー判定はrunner/scraper側で安定済み。ここでは既存フラグだけ見る。
    if bool(_get(candidate, "is_following", False)):
        return "フォロー中"

    if bool(_get(candidate, "is_ad", False)):
        return "広告/PR"

    if _verified_flag(candidate):
        return "認証/青チェック"


    # ────────────────────────────────────────────────────────────────
    # SECTION: フォロワー上限超過 + 広告系キーワード
    # ────────────────────────────────────────────────────────────────
    # フォロワー上限。プロフィール取得済みの場合のみ効く
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

    # 広告/PR。pr/ad単体は誤爆が多いので入れない
    ad_words = [
        "広告", "promotion", "promoted", "sponsored", "スポンサー", "提供", "案件",
        "タイアップ", "企業案件", "#ad", "#pr", "paid partnership", "shop now",
        "購入はこちら", "詳細はこちら", "キャンペーン", "無料体験", "資料請求",
        "セール", "割引", "クーポン", "予約受付", "販売中",
    ]
    hit = _contains_any(text, ad_words + _load_extra_words(rules, "ad_keywords"))
    if hit:
        return "広告/PR"


    # ────────────────────────────────────────────────────────────────
    # SECTION: 公式/法人系キーワード
    # ────────────────────────────────────────────────────────────────
    # 公式/企業/ブランド/メディア/店舗/採用/団体っぽいアカウント
    # inc/tv/ai/運営/グループ単体は誤爆が多いため入れない
    official_words = [
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
    hit = _contains_any(text, official_words + _load_extra_words(rules, "official_keywords"))
    if hit:
        return "公式/企業系(" + hit + ")"


    # ────────────────────────────────────────────────────────────────
    # SECTION: 年齢 + 外国語 + 事務所系ワード
    # ────────────────────────────────────────────────────────────────
    # 年齢/学生
    r = _age_ng(text)
    if r:
        return r

    # 外国語/海外
    if _looks_like_foreign(text):
        return "外国語/海外"

    # 他事務所/所属系
    agency_words = [
        "所属", "事務所所属", "ライバー事務所", "公式ライバー", "認証ライバー",
        "seju", "asobinext", "vaz", "grove", "avex", "ppp studio", "luv", "studio15",
        "321inc", "live事務所", "liver office", "liveroffice", "マネージャー", "manager",
        "nextwave", "neobright", "palmu", "pococha", "17live", "イチナナ",
    ]
    hit = _contains_any(text, agency_words + _load_extra_words(rules, "agency_keywords"))
    if hit:
        return "他事務所/所属系(" + hit + ")"


    # ────────────────────────────────────────────────────────────────
    # SECTION: Live / Music(2000+ アーティスト) / Game / Pet / Food / general NG
    # ────────────────────────────────────────────────────────────────
    # 配信/LIVE/既存ライバー系
    live_words = [
        "配信中", "配信者", "配信垢", "配信アカウント", "ライブ配信", "live配信",
        "tiktok live", "tiktoklive", "ライバー", "17ライブ", "pococha", "ポコチャ",
        "showroom", "ふわっち", "ツイキャス", "ミクチャ", "palmu", "iriam",
        "グループ配信",
    ]
    hit = _contains_any(text, live_words + _load_extra_words(rules, "live_keywords"))
    if hit:
        return "配信/LIVE系(" + hit + ")"

    # 音楽/歌詞/外部映像/推し/アイドル/切り抜き
    music_words = [
        "歌詞動画", "歌詞", "lyrics", "lyric", "lyric video", "弾き語り", "歌ってみた",
        "cover", "カバー", "mv", "pv", "music video", "作曲", "編曲", "同時再生",
        "比較してみた", "切り抜き", "文字起こし", "転載", "拾い画", "拾い動画",
        "外部映像", "ライブ映像", "live映像", "ステージ", "マイク", "ピンマイク",
         "アーティスト", "推し", "映画", "ドラマ", "アニメ", "漫画",
        "大森元貴", "大森元気", "mrs. green apple", "ミセス", "sekai no owari",
        "セカオワ", "嵐", "love so sweet", "babymonster", "初音ミク", "名探偵コナン",
        "kiminitodoke", "君に届け", "naruto", "anime", "contentcreator",
        "最終未来少女", "地下アイドル", "アイドルグループ", "女優", "俳優", "芸能人",
        "芸能", "タレント", "舞台", "出演", "ファンアカウント",
        "blackpink",
        "マカロニえんぴつ",
        "akumanoko",
        "attackontitan",
        "shingekinokyojin",
        "進撃の巨人",
        "idol glow",
        "idolglo",
        "berry表記",
        "洋楽",
        "洋楽和訳",
        "洋楽紹介",
        "洋楽おすすめ",
        "和訳動画",
        "水曜日のダウンタウン",
        "浜田雅功",
        "松本人志",
        "aiko",
        "kisshug",
        "キスハグ",
        "=LOVE",
        "イコラブ",
        "佐々木舞香",
        "大谷映美里",
        "大場花菜",
        "音嶋莉沙",
        "齋藤樹愛羅",
        "髙松瞳",
        "高松瞳",
        "瀧脇笙古",
        "野口衣織",
        "諸橋沙夏",
        "山本杏奈",
        "≠ME",
        "ノイミー",
        "尾木波菜",
        "落合希来里",
        "蟹沢萌子",
        "河口夏音",
        "川中子奈月心",
        "櫻井もも",
        "菅波美玲",
        "鈴木瞳美",
        "谷崎早耶",
        "冨田菜々風",
        "永田詩央里",
        "本田珠由記",
        "≒JOY",
        "ニアジョイ",
        "逢田珠里依",
        "天野香乃愛",
        "市原愛弓",
        "江角怜音",
        "大信田美月",
        "大西葵",
        "小澤愛実",
        "高橋舞",
        "藤沢莉子",
        "村山結香",
        "山田杏佳",
        "山野愛月",
        "乃木坂46",
        "乃木坂",
        "櫻坂46",
        "櫻坂",
        "日向坂46",
        "日向坂",
        "井上和",
        "遠藤さくら",
        "賀喜遥香",
        "筒井あやめ",
        "久保史緒里",
        "梅澤美波",
        "与田祐希",
        "山下美月",
        "齋藤飛鳥",
        "白石麻衣",
        "西野七瀬",
        "生田絵梨花",
        "森田ひかる",
        "山﨑天",
        "山崎天",
        "田村保乃",
        "藤吉夏鈴",
        "守屋麗奈",
        "小林由依",
        "渡邉理佐",
        "菅井友香",
        "小坂菜緒",
        "金村美玖",
        "河田陽菜",
        "丹生明里",
        "齊藤京子",
        "加藤史帆",
        "佐々木美玲",
        "AKB48",
        "AKB",
        "小栗有以",
        "倉野尾成美",
        "村山彩希",
        "柏木由紀",
        "本田仁美",
        "NMB48",
        "HKT48",
        "SKE48",
        "STU48",
        "NGT48",
        "FRUITS ZIPPER",
        "ふるっぱー",
        "櫻井優衣",
        "鎮西寿々歌",
        "松本かれん",
        "月足天音",
        "仲川瑠夏",
        "真中まな",
        "早瀬ノエル",
        "高嶺のなでしこ",
        "たかねこ",
        "松本ももな",
        "橋本桃呼",
        "ME:I",
        "ミーアイ",
        "笠原桃奈",
        "村上璃杏",
        "櫻井美羽",
        "石井蘭",
        "山本すず",
        "NiziU",
        "ニジュー",
        "TWICE",
        "BLACKPINK",
        "IVE",
        "NewJeans",
        "LE SSERAFIM",
        "ILLIT",
    ]
    hit = _contains_any(text, music_words + _load_extra_words(rules, "music_keywords"))
    if hit:
        return "音楽/外部映像系(" + hit + ")"

    # ゲーム系
    game_words = [
        "ゲーム", "ゲーム実況", "apex", "荒野行動", "原神", "ポケモン", "スプラトゥーン",
        "プロセカ", "フォートナイト", "minecraft", "マイクラ", "valorant", "モンスト",
    ]
    hit = _contains_any(text, game_words + _load_extra_words(rules, "game_keywords"))
    if hit:
        return "ゲーム系(" + hit + ")"

    # 動物/猫/犬/ペット系
    pet_words = [
        "猫", "ねこ", "ネコ", "猫のいる生活", "猫好きさんと繋がりたい", "三毛猫", "保護猫",
        "犬", "いぬ", "イヌ", "dog", "cat", "ハムスター", "うさぎ", "bunnies", "ペット", "動物",
        "ハリネズミ",
        "はりねずみ",
        "hedgehog",
        "柴犬",
        "しばいぬ",
        "shibainu",
        "shiba inu",
    ]
    hit = _contains_any(text, pet_words + _load_extra_words(rules, "pet_keywords"))
    if hit:
        return "動物/ペット系(" + hit + ")"

    # 食べ物/料理/グルメ。料理単体は誤爆が多いので入れない
    food_words = [
        "ラーメン", "カレー", "グルメ", "飯テロ", "食べ歩き", "自炊", "レシピ", "スイーツ", "ランチ", "ディナー", "居酒屋", "焼肉", "寿司",
        "沖縄そば", "飲食店", "レストラン", "食堂", "日本美食", "美食", "そば", "うどん", "定食",
        "カフェ巡り",
        "カフェ紹介",
        "カフェメニュー",
        "カフェランチ",
        "カフェ飯",
    ]
    hit = _contains_any(text, food_words + _load_extra_words(rules, "food_keywords"))
    if hit:
        return "食べ物/料理系(" + hit + ")"

    # その他NG
    general_words = [
        "お●2", "もっと載せてる", "dm", "独身", "婚活", "恋活", "副業勧誘", "投資",
        "fx", "仮想通貨", "稼げる", "稼ぎ方", "情報商材",
        "マスク", "顔隠し", "顔出しなし", "顔なし", "雰囲気だけ",
        "2ch",
        "5ch",
        "shorts",
        "ネット系",
        "合成",
        "モザイク",
        "ピクセル",
        "サングラス",
        "キャラクター",
        "アバター",
        "外部メディア",
        "キャラクターイラスト",
        "ハローキティ",
        "キティ",
        "スタンプで隠れ",
        "顔スタンプ",
        "番組切り抜き",
        "テレビ切り抜き",
        "真剣",
        "友達作り",
        "にほん",
        "日本",
        "相互フォロー",
        "フォロバ",
        "フォロー返し",
        "相互垢",
        "フォロバ100",
    ]
    hit = _contains_any(text, general_words + _load_extra_words(rules, "ng_keywords"))
    if hit:
        return "NGワード(" + hit + ")"



    # ────────────────────────────────────────────────────────────────
    # SECTION: v5 ハッシュコンボ + 数字のみタグ + 空 Bio/タグ
    # ────────────────────────────────────────────────────────────────
    # V5共有前保証: ハッシュタグ 美人 + モデル + かわいい の3点セット除外
    try:
        _v5_combo_tags_raw = (
            _get(candidate, "hashtags", None)
            or _get(candidate, "hashtag", None)
            or _get(candidate, "tags", None)
            or _get(candidate, "tag_text", None)
            or _get(candidate, "hashtag_text", None)
            or ""
        )
    except Exception:
        _v5_combo_tags_raw = (
            getattr(candidate, "hashtags", None)
            or getattr(candidate, "hashtag", None)
            or getattr(candidate, "tags", None)
            or getattr(candidate, "tag_text", None)
            or getattr(candidate, "hashtag_text", None)
            or ""
        )
    if isinstance(_v5_combo_tags_raw, (list, tuple, set)):
        _v5_combo_tags = " ".join([str(x) for x in _v5_combo_tags_raw])
    else:
        _v5_combo_tags = str(_v5_combo_tags_raw or "")
    if all(_kw in _v5_combo_tags for _kw in ["美人", "モデル", "かわいい"]):
        return "ハッシュタグNG(美人/モデル/かわいい)"

    # V5共有前保証: ハッシュタグが数字だけ、かつプロフィール紹介文が空欄なら除外
    try:
        _v5_num_bio = (
            _get(candidate, "profile_bio", None)
            or _get(candidate, "bio", None)
            or _get(candidate, "signature", None)
            or _get(candidate, "profile_text", None)
            or _get(candidate, "description", None)
            or _get(candidate, "desc", None)
            or ""
        )
        _v5_num_tags_raw = (
            _get(candidate, "hashtags", None)
            or _get(candidate, "hashtag", None)
            or _get(candidate, "tags", None)
            or _get(candidate, "tag_text", None)
            or _get(candidate, "hashtag_text", None)
            or ""
        )
    except Exception:
        _v5_num_bio = (
            getattr(candidate, "profile_bio", None)
            or getattr(candidate, "bio", None)
            or getattr(candidate, "signature", None)
            or getattr(candidate, "profile_text", None)
            or getattr(candidate, "description", None)
            or getattr(candidate, "desc", None)
            or ""
        )
        _v5_num_tags_raw = (
            getattr(candidate, "hashtags", None)
            or getattr(candidate, "hashtag", None)
            or getattr(candidate, "tags", None)
            or getattr(candidate, "tag_text", None)
            or getattr(candidate, "hashtag_text", None)
            or ""
        )
    if isinstance(_v5_num_tags_raw, (list, tuple, set)):
        _v5_num_tags = " ".join([str(x) for x in _v5_num_tags_raw]).strip()
    else:
        _v5_num_tags = str(_v5_num_tags_raw or "").strip()
    _v5_num_norm = _v5_num_tags.translate(str.maketrans("０１２３４５６７８９", "0123456789"))
    _v5_num_norm = re.sub(r"[#＃\s,，、/／｜|・.．。:_\-－ー]+", "", _v5_num_norm)
    if str(_v5_num_bio).strip() == "" and _v5_num_tags != "" and _v5_num_norm.isdigit():
        return "ハッシュタグ数字のみ/プロフィール紹介文空欄"

    # V5共有前保証: ハッシュタグとプロフィール紹介文がどちらも空欄なら除外
    try:
        _v5_empty_bio = (
            _get(candidate, "profile_bio", None)
            or _get(candidate, "bio", None)
            or _get(candidate, "signature", None)
            or _get(candidate, "profile_text", None)
            or _get(candidate, "description", None)
            or _get(candidate, "desc", None)
            or ""
        )
        _v5_empty_tags_raw = (
            _get(candidate, "hashtags", None)
            or _get(candidate, "hashtag", None)
            or _get(candidate, "tags", None)
            or _get(candidate, "tag_text", None)
            or _get(candidate, "hashtag_text", None)
            or ""
        )
    except Exception:
        _v5_empty_bio = (
            getattr(candidate, "profile_bio", None)
            or getattr(candidate, "bio", None)
            or getattr(candidate, "signature", None)
            or getattr(candidate, "profile_text", None)
            or getattr(candidate, "description", None)
            or getattr(candidate, "desc", None)
            or ""
        )
        _v5_empty_tags_raw = (
            getattr(candidate, "hashtags", None)
            or getattr(candidate, "hashtag", None)
            or getattr(candidate, "tags", None)
            or getattr(candidate, "tag_text", None)
            or getattr(candidate, "hashtag_text", None)
            or ""
        )
    if isinstance(_v5_empty_tags_raw, (list, tuple, set)):
        _v5_empty_tags = " ".join([str(x) for x in _v5_empty_tags_raw]).strip()
    else:
        _v5_empty_tags = str(_v5_empty_tags_raw or "").strip()
    if str(_v5_empty_bio).strip() == "" and _v5_empty_tags == "":
        return "ハッシュタグ/プロフィール紹介文空欄"

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
