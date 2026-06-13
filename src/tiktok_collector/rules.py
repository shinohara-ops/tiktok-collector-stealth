
from __future__ import annotations

import re
from typing import Optional

# 共有ヘルパと Sheets プロバイダ状態(set_ng_keyword_provider / _check_scoped_ng_words 等)
# は _rules_parts/_helpers.py に集約。後方互換のため rules モジュールから再 export する
# (main.py が rules.set_ng_keyword_provider(...) を呼ぶ運用)。
from ._rules_parts._helpers import (
    _get,
    _norm,
    _candidate_text,
    _contains_any,
    _load_extra_words,
    _foreign_score,
    _looks_like_foreign,
    _age_ng,
    _verified_flag,
    _check_scoped_ng_words,
    set_ng_keyword_provider,
    set_ng_keyword_meta_provider,
)

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
from ._rules_parts import user_digits_id as _user_digits_id
from ._rules_parts import multi_person as _multi_person
from ._rules_parts import fan_account as _fan_account


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
    # SECTION: アイドル/タレントのファン・応援アカウント
    # → src/tiktok_collector/_rules_parts/fan_account.py に抽出済
    # `colored_leak_v2` の「ランダムID/海外・量産寄り」より先に置く必要がある。
    # 後ろに置くと AI override 経由で nano が顔だけ見て採用してしまう。
    # ────────────────────────────────────────────────────────────────
    if (r := _fan_account.check(_cs_bio_s, _cs_tags)) is not None:
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
    if (r := _account_meta_basic.check(candidate)) is not None:
        return r


    # ────────────────────────────────────────────────────────────────
    # SECTION: フォロワー上限超過 + 広告/PR + 公式/法人系
    # → src/tiktok_collector/_rules_parts/follower_ad_official.py に抽出済
    # ────────────────────────────────────────────────────────────────
    if (r := _follower_ad_official.check(text, candidate, rules)) is not None:
        return r


    # ────────────────────────────────────────────────────────────────
    # SECTION: 年齢 + 外国語 + 事務所系
    # → src/tiktok_collector/_rules_parts/age_foreign_agency.py に抽出済
    # ────────────────────────────────────────────────────────────────
    if (r := _age_foreign_agency.check(text, rules)) is not None:
        return r


    # ────────────────────────────────────────────────────────────────
    # SECTION: Live / Music(2000+ アーティスト) / Game / Pet / Food / general NG
    # → src/tiktok_collector/_rules_parts/category_keywords.py に抽出済
    # ────────────────────────────────────────────────────────────────
    if (r := _category_keywords.check(text, rules)) is not None:
        return r


    # ────────────────────────────────────────────────────────────────
    # SECTION: v5 ハッシュコンボ + 数字のみタグ + 空 Bio/タグ
    # → src/tiktok_collector/_rules_parts/v5_final_combos.py に抽出済
    # ────────────────────────────────────────────────────────────────
    if (r := _v5_final_combos.check(_cs_bio_s, _cs_tags)) is not None:
        return r


    # ────────────────────────────────────────────────────────────────
    # SECTION: user + 6桁以上の数字 のデフォルトID
    # → src/tiktok_collector/_rules_parts/user_digits_id.py に抽出済
    # ────────────────────────────────────────────────────────────────
    if (r := _user_digits_id.check(_cs_uid_s)) is not None:
        return r

    # ────────────────────────────────────────────────────────────────
    # SECTION: 複数人運営アカウント(夫婦/カップル/家族/双子 等)
    # → src/tiktok_collector/_rules_parts/multi_person.py に抽出済
    # ────────────────────────────────────────────────────────────────
    if (r := _multi_person.check(_cs_bio_s)) is not None:
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
