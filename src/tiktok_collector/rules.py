
from __future__ import annotations

import re
from typing import Callable, Optional


# Sheets「NGワード」タブからカテゴリ別 NG ワードを供給するためのフック。
# main.py 起動時に set_ng_keyword_provider() で登録する。未登録なら従来通り
# config.yaml と固定リストのみで動作。
_ng_keyword_provider: Optional[Callable[[str], list[str]]] = None


def set_ng_keyword_provider(provider: Optional[Callable[[str], list[str]]]) -> None:
    global _ng_keyword_provider
    _ng_keyword_provider = provider


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

    for _w in ['テンプレートお借りしました', 'テンプレお借りしました', 'お借りしました', 'この歌好き', 'この音源好き', '音源好き', '黒毛和牛上塩タン焼680円', '黒毛和牛上塩タン焼', 'シャドバン', 'シャドウバン', 'シャドバン解除', 'げろげろぴー', 'unsunghero', 'runaar', '村谷はるな', 'はるち']:
        _ws = str(_w or "").strip()
        if _ws and _ws.lower() in _cs_low:
            return f"類似除外({_ws})"

    if re.search(r"(?<!\d)(?:08|09)\s*[♡❤♥💕💖/／・,，、.．\-－_\s]+\s*(?:08|09)(?!\d)", _cs_digit_text):
        return "未成年系NG(08/09ペア表記)"

    _cs_tokens = [t for t in re.split(r"[#＃\s,，、/／｜|・.．。:_\-－ー♡❤♥💕💖]+", _cs_digit_text) if t]
    if "08" in _cs_tokens:
        return "未成年系NG(08)"
    if "09" in _cs_tokens:
        return "未成年系NG(09)"

    _cs_generic_hit = None
    _cs_noise_count = 0
    for _w in ['capcut', 'tiktok流行りダンス', '流行りダンス', '流行りdance', '落書き', 'fyp', 'fypシ', 'おすすめ', 'バズれ', 'バズりたい', 'テンプレ', 'この歌', 'この音源', '歌詞', '音源', 'ダンス']:
        _ws = str(_w or "").strip()
        if _ws and _ws.lower() in _cs_low:
            _cs_noise_count += 1
            if _cs_generic_hit is None:
                _cs_generic_hit = _ws

    if re.search(r"(?:08|09)$", _cs_uid_s) and _cs_bio_empty_or_emoji and _cs_generic_hit:
        return f"未成年/量産系NG(08/09末尾ID+短文Bio+{_cs_generic_hit})"

    if _cs_bio_empty_or_emoji and _cs_noise_count >= 2:
        return "量産系NG(短文Bio+ノイズタグ複数)"

    _cs_tags_norm = re.sub(r"\s+", "", _cs_tags.lower())
    _cs_bio_norm = re.sub(r"\s+", "", _cs_bio_s.lower())
    if _cs_tags_norm and _cs_tags_norm == _cs_bio_norm and _cs_generic_hit:
        return "量産系NG(ハッシュタグとBio同一)"


    # 追加NG: 学校行事・学年・未成年年齢表記
    _school_age_ng_words = ['文化祭', '体育祭', '修学旅行', '高二', '高一', '中三', '中二', '中一', '17歳', '17才', '17サイ', '17❤︎', '17❤', '17♡', '17♥', '16歳', '16才', '16サイ', '16❤︎', '16❤', '16♡', '16♥', '15歳', '15才', '15サイ', '15❤︎', '15❤', '15♡', '15♥', '14歳', '14才', '14サイ', '14❤︎', '14❤', '14♡', '14♥', '13歳', '13才', '13サイ', '13❤︎', '13❤', '13♡', '13♥', 'えふじぇーしー', 'えすじぇーしー', 'えるじぇーしー', 'えすじぇーけー', 'えふじぇーけー', '11y', '12y', '13y', '14y', '15y', '16y', '17y']
    _school_age_text = str(text or "")
    _school_age_norm = _school_age_text.translate(str.maketrans("０１２３４５６７８９", "0123456789"))
    _school_age_low = _school_age_norm.lower()

    for _school_age_w in _school_age_ng_words:
        _school_age_ws = str(_school_age_w or "").strip()
        if _school_age_ws and _school_age_ws.lower() in _school_age_low:
            return f"NGワード({_school_age_ws})"

    # (11)〜(17)、（11）〜（17）
    if re.search(r"[\(（]\s*(?:11|12|13|14|15|16|17)\s*[\)）]", _school_age_norm):
        return "未成年系NG(括弧年齢表記)"

    # 11y〜17y。英単語の一部誤爆を避けるため前後を英数字以外に限定
    if re.search(r"(?<![a-zA-Z0-9])(?:11|12|13|14|15|16|17)\s*y(?![a-zA-Z0-9])", _school_age_low):
        return "未成年系NG(11y-17y)"

    # 13〜17 + ハート/装飾。17❤︎などの表記揺れも拾う
    if re.search(r"(?<!\d)(?:13|14|15|16|17)\s*[❤♡♥💕💖💗💓💞]", _school_age_norm):
        return "未成年系NG(年齢+ハート表記)"


    # 2764行目以降の色付きアカウントID除外
    _colored_excluded_ids_2764 = ['na_.xl72', 'm3i.64', 'o8_kko7', 'qxlyg', 'antowanett_88', 'naru13595', '14376_', '_________0.00', 'q_r__zx', 'parurun_chan1', 'sfffed55', 'o____12m', 'kuu_86369']
    try:
        _candidate_uid_2764 = (
            _get(candidate, "unique_id", None)
            or _get(candidate, "user_id", None)
            or _get(candidate, "id", None)
            or ""
        )
    except Exception:
        _candidate_uid_2764 = (
            getattr(candidate, "unique_id", None)
            or getattr(candidate, "user_id", None)
            or getattr(candidate, "id", None)
            or ""
        )
    _candidate_uid_2764 = str(_candidate_uid_2764 or "").strip().replace("@", "")
    if _candidate_uid_2764 in _colored_excluded_ids_2764:
        return f"色付き除外ID({_candidate_uid_2764})"


    # 追加除外: 08/09末尾ID + 絵文字Bio + テンプレ/歌系タグ
    try:
        _ts_uid = (
            _get(candidate, "unique_id", None)
            or _get(candidate, "user_id", None)
            or _get(candidate, "id", None)
            or ""
        )
        _ts_name = (
            _get(candidate, "display_name", None)
            or _get(candidate, "nickname", None)
            or _get(candidate, "name", None)
            or ""
        )
        _ts_bio = (
            _get(candidate, "profile_bio", None)
            or _get(candidate, "bio", None)
            or _get(candidate, "signature", None)
            or _get(candidate, "profile_text", None)
            or _get(candidate, "description", None)
            or _get(candidate, "desc", None)
            or ""
        )
        _ts_tags_raw = (
            _get(candidate, "hashtags", None)
            or _get(candidate, "hashtag", None)
            or _get(candidate, "tags", None)
            or _get(candidate, "tag_text", None)
            or _get(candidate, "hashtag_text", None)
            or ""
        )
    except Exception:
        _ts_uid = (
            getattr(candidate, "unique_id", None)
            or getattr(candidate, "user_id", None)
            or getattr(candidate, "id", None)
            or ""
        )
        _ts_name = (
            getattr(candidate, "display_name", None)
            or getattr(candidate, "nickname", None)
            or getattr(candidate, "name", None)
            or ""
        )
        _ts_bio = (
            getattr(candidate, "profile_bio", None)
            or getattr(candidate, "bio", None)
            or getattr(candidate, "signature", None)
            or getattr(candidate, "profile_text", None)
            or getattr(candidate, "description", None)
            or getattr(candidate, "desc", None)
            or ""
        )
        _ts_tags_raw = (
            getattr(candidate, "hashtags", None)
            or getattr(candidate, "hashtag", None)
            or getattr(candidate, "tags", None)
            or getattr(candidate, "tag_text", None)
            or getattr(candidate, "hashtag_text", None)
            or ""
        )

    if isinstance(_ts_tags_raw, (list, tuple, set)):
        _ts_tags = " ".join([str(x) for x in _ts_tags_raw]).strip()
    else:
        _ts_tags = str(_ts_tags_raw or "").strip()

    _ts_uid_s = str(_ts_uid or "").strip().replace("@", "")
    _ts_bio_s = str(_ts_bio or "").strip()
    _ts_full = " ".join([_ts_uid_s, str(_ts_name or ""), _ts_tags, _ts_bio_s])
    _ts_low = _ts_full.lower()

    for _w in ['テンプレートお借りしました', 'テンプレお借りしました', 'この歌好き', '黒毛和牛上塩タン焼680円', '黒毛和牛上塩タン焼', '村谷はるな', 'はるち']:
        _ws = str(_w or "").strip()
        if _ws and _ws.lower() in _ts_low:
            return f"NGワード({_ws})"

    # 08/09末尾ID + 絵文字のみ/短すぎるBio + テンプレ/歌/流行り系タグは未成年・量産ノイズとして除外
    _ts_bio_without_symbols = re.sub(r"[\W_\s]+", "", _ts_bio_s, flags=re.UNICODE)
    _ts_emoji_or_too_short_bio = (_ts_bio_s == "") or (len(_ts_bio_without_symbols) == 0) or (len(_ts_bio_s) <= 2)
    _ts_template_song_like = re.search(r"(テンプレ|お借りしました|この歌|歌好き|流行り|流行|capcut|落書き)", _ts_full, flags=re.I) is not None
    if re.search(r"(?:08|09)$", _ts_uid_s) and _ts_emoji_or_too_short_bio and _ts_template_song_like:
        return "未成年/量産系NG(08/09末尾ID+短文Bio+テンプレ歌系)"


    # 追加除外: 09-08系 + シャドバン + CapCut流行りダンス系
    try:
        _tp_uid = (
            _get(candidate, "unique_id", None)
            or _get(candidate, "user_id", None)
            or _get(candidate, "id", None)
            or ""
        )
        _tp_name = (
            _get(candidate, "display_name", None)
            or _get(candidate, "nickname", None)
            or _get(candidate, "name", None)
            or ""
        )
        _tp_bio = (
            _get(candidate, "profile_bio", None)
            or _get(candidate, "bio", None)
            or _get(candidate, "signature", None)
            or _get(candidate, "profile_text", None)
            or _get(candidate, "description", None)
            or _get(candidate, "desc", None)
            or ""
        )
        _tp_tags_raw = (
            _get(candidate, "hashtags", None)
            or _get(candidate, "hashtag", None)
            or _get(candidate, "tags", None)
            or _get(candidate, "tag_text", None)
            or _get(candidate, "hashtag_text", None)
            or ""
        )
    except Exception:
        _tp_uid = (
            getattr(candidate, "unique_id", None)
            or getattr(candidate, "user_id", None)
            or getattr(candidate, "id", None)
            or ""
        )
        _tp_name = (
            getattr(candidate, "display_name", None)
            or getattr(candidate, "nickname", None)
            or getattr(candidate, "name", None)
            or ""
        )
        _tp_bio = (
            getattr(candidate, "profile_bio", None)
            or getattr(candidate, "bio", None)
            or getattr(candidate, "signature", None)
            or getattr(candidate, "profile_text", None)
            or getattr(candidate, "description", None)
            or getattr(candidate, "desc", None)
            or ""
        )
        _tp_tags_raw = (
            getattr(candidate, "hashtags", None)
            or getattr(candidate, "hashtag", None)
            or getattr(candidate, "tags", None)
            or getattr(candidate, "tag_text", None)
            or getattr(candidate, "hashtag_text", None)
            or ""
        )

    if isinstance(_tp_tags_raw, (list, tuple, set)):
        _tp_tags = " ".join([str(x) for x in _tp_tags_raw]).strip()
    else:
        _tp_tags = str(_tp_tags_raw or "").strip()

    _tp_full = " ".join([
        str(_tp_uid or ""),
        str(_tp_name or ""),
        _tp_tags,
        str(_tp_bio or "")
    ])
    _tp_low = _tp_full.lower()

    for _w in ['シャドバン', 'シャドウバン', 'げろげろぴー', 'capcut', 'tiktok流行りダンス', '流行りダンス', '流行りdance', 'unsunghero', 'runaar']:
        _ws = str(_w or "").strip()
        if _ws and _ws.lower() in _tp_low:
            return f"NGワード({_ws})"

    # 09♡08 / 08♡09 / 09・08 / 08/09 など、未成年年度ペアっぽい表記を除外
    _tp_digit_text = _tp_full.translate(str.maketrans("０１２３４５６７８９", "0123456789"))
    if re.search(r"(?<!\d)(?:08|09)\s*[♡❤♥💕💖/／・,，、.．\-－_\s]+\s*(?:08|09)(?!\d)", _tp_digit_text):
        return "未成年系NG(08/09ペア表記)"

    # bioやタグ内に 08 / 09 が記号付きで単体出現するケースも除外
    _tp_tokens = [t for t in re.split(r"[#＃\s,，、/／｜|・.．。:_\-－ー♡❤♥💕💖]+", _tp_digit_text) if t]
    if "08" in _tp_tokens:
        return "未成年系NG(08)"
    if "09" in _tp_tokens:
        return "未成年系NG(09)"


    # 追加NGワード: No bio yet
    if "no bio yet" in text.lower():
        return "NGワード(No bio yet)"


    # 1650行目以降の色付きアカウントID除外
    _colored_excluded_ids_1650 = ['ngminhchi335', 'muxi6699', 'osakana1225', '_ll.s10', 'hozonyoudesu0', 'neko22momo', '_n0zk', 'maya181526', 'xrbdwqgoceh', 'umebosi_05', 'mio0403018', 'uu1313.t', '26zixy', 'minpuri330']
    try:
        _candidate_uid_1650 = (
            _get(candidate, "unique_id", None)
            or _get(candidate, "user_id", None)
            or _get(candidate, "id", None)
            or ""
        )
    except Exception:
        _candidate_uid_1650 = (
            getattr(candidate, "unique_id", None)
            or getattr(candidate, "user_id", None)
            or getattr(candidate, "id", None)
            or ""
        )
    _candidate_uid_1650 = str(_candidate_uid_1650 or "").strip().replace("@", "")
    if _candidate_uid_1650 in _colored_excluded_ids_1650:
        return f"色付き除外ID({_candidate_uid_1650})"


    # 色付き行の類似アカウントを落とす汎用除外パッチ v2
    try:
        _gc_uid = (
            _get(candidate, "unique_id", None)
            or _get(candidate, "user_id", None)
            or _get(candidate, "id", None)
            or ""
        )
        _gc_name = (
            _get(candidate, "display_name", None)
            or _get(candidate, "nickname", None)
            or _get(candidate, "name", None)
            or ""
        )
        _gc_bio = (
            _get(candidate, "profile_bio", None)
            or _get(candidate, "bio", None)
            or _get(candidate, "signature", None)
            or _get(candidate, "profile_text", None)
            or _get(candidate, "description", None)
            or _get(candidate, "desc", None)
            or ""
        )
        _gc_tags_raw = (
            _get(candidate, "hashtags", None)
            or _get(candidate, "hashtag", None)
            or _get(candidate, "tags", None)
            or _get(candidate, "tag_text", None)
            or _get(candidate, "hashtag_text", None)
            or ""
        )
    except Exception:
        _gc_uid = (
            getattr(candidate, "unique_id", None)
            or getattr(candidate, "user_id", None)
            or getattr(candidate, "id", None)
            or ""
        )
        _gc_name = (
            getattr(candidate, "display_name", None)
            or getattr(candidate, "nickname", None)
            or getattr(candidate, "name", None)
            or ""
        )
        _gc_bio = (
            getattr(candidate, "profile_bio", None)
            or getattr(candidate, "bio", None)
            or getattr(candidate, "signature", None)
            or getattr(candidate, "profile_text", None)
            or getattr(candidate, "description", None)
            or getattr(candidate, "desc", None)
            or ""
        )
        _gc_tags_raw = (
            getattr(candidate, "hashtags", None)
            or getattr(candidate, "hashtag", None)
            or getattr(candidate, "tags", None)
            or getattr(candidate, "tag_text", None)
            or getattr(candidate, "hashtag_text", None)
            or ""
        )

    if isinstance(_gc_tags_raw, (list, tuple, set)):
        _gc_tags = " ".join([str(x) for x in _gc_tags_raw]).strip()
    else:
        _gc_tags = str(_gc_tags_raw or "").strip()

    _gc_uid_s = str(_gc_uid or "").strip().replace("@", "")
    _gc_name_s = str(_gc_name or "").strip()
    _gc_bio_s = str(_gc_bio or "").strip()
    _gc_full = " ".join([_gc_uid_s, _gc_name_s, _gc_tags, _gc_bio_s])
    _gc_low = _gc_full.lower()
    _gc_tags_low = _gc_tags.lower()

    _gc_has_japanese = re.search(r"[ぁ-んァ-ヶ一-龥]", _gc_full) is not None
    _gc_has_kana = re.search(r"[ぁ-んァ-ヶ]", _gc_full) is not None
    _gc_has_ascii_tags = re.search(r"[a-zA-Z]", _gc_tags) is not None
    _gc_has_ascii_bio = re.search(r"[a-zA-Z]", _gc_bio_s) is not None

    # A. 明示NG。インスタ/ID誘導と短すぎる@Bioは除外しない。
    for _gc_w in ['絡み募', '絡み募集', '地雷', 'xuhuong', 'gaixinh', 'xinhdep', 'cewek', 'wanita', 'cantik', 'mencari', 'daun muda', 'vaycongchua', 'phongcachphap', 'bachnguyetquang', 'stylenangtho', 'outfitlangman', 'cortis', 'onephony', '田島櫻子', 'slipknot', 'metal', 'affiliate', 'affiliatemarketing', 'no bio yet', 'No bio yet', '女装', '女装男子', '男の娘', '偽娘', 'ニューハーフ']:
        _gc_ws = str(_gc_w or "").strip()
        if _gc_ws and _gc_ws.lower() in _gc_low:
            return f"類似除外({_gc_ws})"

    # B. 未成年系。08/09はハッシュタグ単体トークンで除外。15さい/15歳なども除外。
    _gc_tags_norm_digits = _gc_tags.translate(str.maketrans("０１２３４５６７８９", "0123456789"))
    _gc_tag_tokens = [t for t in re.split(r"[#＃\s,，、/／｜|・.．。:_\-－ー]+", _gc_tags_norm_digits) if t]
    if "08" in _gc_tag_tokens:
        return "ハッシュタグNG(08/未成年系)"
    if "09" in _gc_tag_tokens:
        return "ハッシュタグNG(09/未成年系)"

    for _uw in ['未成年', '中学生', '高校生', 'jc', 'jc1', 'jc2', 'jc3', 'jk1', 'jk2', 'jk3', 'fjk', 'sjk', 'ljk', '15さい', '15歳', '15才', '１５さい', '１５歳', '１５才', '14さい', '14歳', '14才', '１４さい', '１４歳', '１４才', '13さい', '13歳', '13才', '１３さい', '１３歳', '１３才', '16さい', '16歳', '16才', '１６さい', '１６歳', '１６才', '17さい', '17歳', '17才', '１７さい', '１７歳', '１７才']:
        _uws = str(_uw or "").strip()
        if _uws and _uws.lower() in _gc_low:
            return f"未成年系NG({_uws})"

    _gc_age_text = _gc_full.translate(str.maketrans("０１２３４５６７８９", "0123456789"))
    if re.search(r"(?<![0-9])(?:1[0-7]|[0-9])\s*(?:歳|才|さい)(?![0-9])", _gc_age_text):
        return "未成年系NG(年齢表記)"

    # C. 外部リンク誘導。ただし litlink / lit.link は除外しない
    _gc_has_litlink = ("lit.link" in _gc_low) or ("litlink" in _gc_low)
    for _gc_link in ["facebook.com", "mibextid", "onlyfans", "ofans", "fansly", "beacons.ai", "linktr.ee"]:
        if _gc_link in _gc_low and not _gc_has_litlink:
            return f"外部リンクNG({_gc_link})"

    # D. ランダムID + 日本語要素が薄い/海外っぽいもの
    _gc_uid_clean = re.sub(r"[^a-zA-Z0-9]", "", _gc_uid_s).lower()
    _gc_uid_has_letter = re.search(r"[a-z]", _gc_uid_clean) is not None
    _gc_uid_has_digit = re.search(r"[0-9]", _gc_uid_clean) is not None
    _gc_uid_has_sep = ("_" in _gc_uid_s) or ("." in _gc_uid_s) or ("-" in _gc_uid_s)
    if len(_gc_uid_clean) >= 7 and _gc_uid_has_letter and _gc_uid_has_digit and not _gc_uid_has_sep:
        if not _gc_has_kana or _gc_bio_s == "" or _gc_has_ascii_tags:
            return "ランダムID/海外・量産寄り"

    # E. 英字タグ中心 + 日本語なし/短文bio
    if _gc_has_ascii_tags and not _gc_has_japanese:
        if _gc_bio_s == "" or len(_gc_bio_s) <= 30:
            return "外国語/海外(英字タグ中心+日本語なし)"

    # F. fyp + 日本語要素が薄い
    if "fyp" in _gc_tags_low and not _gc_has_kana:
        if _gc_bio_s == "" or _gc_has_ascii_bio or re.search(r"[\u4E00-\u9FFF]", _gc_bio_s):
            return "外国語/海外(fyp+日本語要素薄い)"

    # G. 中国語は簡体字/中国語フレーズで除外
    _gc_cn_phrases = ["今天", "也是", "电影", "治愈", "的一天", "关注", "私信", "主页", "置顶", "找我", "美女", "漂亮", "可爱", "点赞", "评论", "转发", "视频", "大家好", "我是", "喜欢"]
    for _gc_cn in _gc_cn_phrases:
        if _gc_cn in _gc_full:
            return f"外国語/海外(中国語:{_gc_cn})"
    _gc_simplified_chars = "这们为热电说话买卖体会觉让从给发欢乐国学广东网写气应旧后边过还进长门"
    if sum(1 for _ch in _gc_simplified_chars if _ch in _gc_full) >= 2:
        return "外国語/海外(中国語/簡体字)"

    # H. 非日本語文字種
    if re.search(r"[\u1000-\u109F\u1780-\u17FF\u0E80-\u0EFF\u0E00-\u0E7F\u0400-\u04FF\u0600-\u06FF\u0900-\u097F]", _gc_full):
        return "外国語/海外(非日本語文字種)"

    # I. 同一英字連続タグ
    if re.search(r"(?i)(?<![a-z])([a-z])\1{7,}(?![a-z])", _gc_tags):
        return "ハッシュタグNG(同一英字連続)"


    # 追加除外: 日本以外の海外アカウント除外強化
    try:
        _nj_uid = (
            _get(candidate, "unique_id", None)
            or _get(candidate, "user_id", None)
            or _get(candidate, "id", None)
            or ""
        )
        _nj_name = (
            _get(candidate, "display_name", None)
            or _get(candidate, "nickname", None)
            or _get(candidate, "name", None)
            or ""
        )
        _nj_bio = (
            _get(candidate, "profile_bio", None)
            or _get(candidate, "bio", None)
            or _get(candidate, "signature", None)
            or _get(candidate, "profile_text", None)
            or _get(candidate, "description", None)
            or _get(candidate, "desc", None)
            or ""
        )
        _nj_tags_raw = (
            _get(candidate, "hashtags", None)
            or _get(candidate, "hashtag", None)
            or _get(candidate, "tags", None)
            or _get(candidate, "tag_text", None)
            or _get(candidate, "hashtag_text", None)
            or ""
        )
    except Exception:
        _nj_uid = (
            getattr(candidate, "unique_id", None)
            or getattr(candidate, "user_id", None)
            or getattr(candidate, "id", None)
            or ""
        )
        _nj_name = (
            getattr(candidate, "display_name", None)
            or getattr(candidate, "nickname", None)
            or getattr(candidate, "name", None)
            or ""
        )
        _nj_bio = (
            getattr(candidate, "profile_bio", None)
            or getattr(candidate, "bio", None)
            or getattr(candidate, "signature", None)
            or getattr(candidate, "profile_text", None)
            or getattr(candidate, "description", None)
            or getattr(candidate, "desc", None)
            or ""
        )
        _nj_tags_raw = (
            getattr(candidate, "hashtags", None)
            or getattr(candidate, "hashtag", None)
            or getattr(candidate, "tags", None)
            or getattr(candidate, "tag_text", None)
            or getattr(candidate, "hashtag_text", None)
            or ""
        )

    if isinstance(_nj_tags_raw, (list, tuple, set)):
        _nj_tags = " ".join([str(x) for x in _nj_tags_raw]).strip()
    else:
        _nj_tags = str(_nj_tags_raw or "").strip()

    _nj_uid_s = str(_nj_uid or "").strip().replace("@", "")
    _nj_name_s = str(_nj_name or "").strip()
    _nj_bio_s = str(_nj_bio or "").strip()
    _nj_full = " ".join([_nj_uid_s, _nj_name_s, _nj_tags, _nj_bio_s])
    _nj_full_lower = _nj_full.lower()
    _nj_bio_lower = _nj_bio_s.lower()
    _nj_tags_lower = _nj_tags.lower()

    for _w in ['feilvbin', '絡み募', 'xuhuong', 'xuhuongtiktok', 'gaixinh', 'gaixinhtiktok', 'xinhdep', 'cewek', 'wanita', 'masih mencari', 'cantik', 'mencari', 'dungmai', 'halinh', 'babygirl', 'bikini', 'follow tui', 'mọi người']:
        _ws = str(_w or "").strip()
        if _ws and _ws.lower() in _nj_full_lower:
            return f"外国語/海外({_ws})"

    # 中国語は、日本語の漢字まで落とさないため、簡体字特有文字/中国語フレーズで判定する
    for _p in ['今天', '也是', '被热', '热可可', '旧电影', '电影', '治愈', '的一天', '关注', '私信', '主页', '置顶', '找我', '美女', '漂亮', '可爱', '点赞', '评论', '转发', '粉丝', '视频', '熱門', '热门', '推荐', '大家好', '我是', '谢谢', '喜欢', '生活', '日常', '女孩', '女生']:
        if _p and _p in _nj_full:
            return f"外国語/海外(中国語:{_p})"

    _cn_simplified_hit = 0
    for _ch in ['这', '们', '为', '热', '电', '说', '话', '买', '卖', '体', '会', '觉', '让', '从', '给', '发', '欢', '乐', '国', '学', '广', '东', '网', '写', '气', '应', '旧', '后', '边', '过', '还', '进', '长', '门']:
        if _ch and _ch in _nj_full:
            _cn_simplified_hit += 1
    if _cn_simplified_hit >= 2:
        return "外国語/海外(中国語/簡体字)"
    # bio内に簡体字特有文字が1つでもあり、日本語かなが無ければ中国語扱い
    if _nj_bio_s and _cn_simplified_hit >= 1 and not re.search(r"[ぁ-んァ-ヶ]", _nj_bio_s):
        return "外国語/海外(中国語/簡体字Bio)"

    # 日本語では通常使わない文字種は強めに除外
    if re.search(r"[\u1000-\u109F\u1780-\u17FF\u0E80-\u0EFF\u0E00-\u0E7F\u0400-\u04FF\u0600-\u06FF\u0900-\u097F]", _nj_full):
        return "外国語/海外(非日本語文字種)"

    # ベトナム語アクセント
    if re.search(r"[ăâêôơưđàáạảãằắặẳẵầấậẩẫèéẹẻẽềếệểễìíịỉĩòóọỏõồốộổỗờớợởỡùúụủũừứựửữỳýỵỷỹ]", _nj_full_lower):
        return "外国語/海外(ベトナム語文字)"

    # 英語はタグ単語だけなら許容。bioやタグが文章っぽい場合だけ除外
    def _nj_english_sentence_like(_s):
        _low = str(_s or "").lower()
        _words = re.findall(r"[a-zA-Z']{2,}", _low)
        if len(_words) >= 6:
            return True
        _hits = 0
        for _ew in ['i', 'you', 'we', 'they', 'he', 'she', 'my', 'your', 'the', 'and', 'to', 'with', 'for', 'from', 'like', 'love', 'dont', "don't", 'cant', "can't", 'can', 'am', 'is', 'are', 'was', 'were', 'be', 'been', 'being', 'have', 'has', 'had', 'me', 'at', 'in', 'on', 'of', 'small', 'talk']:
            if re.search(r"\b" + re.escape(_ew.lower()) + r"\b", _low):
                _hits += 1
        if len(_words) >= 3 and _hits >= 2:
            return True
        if len(_words) >= 3 and re.search(r"[.!?]", _s):
            return True
        return False

    if _nj_english_sentence_like(_nj_bio_s):
        return "外国語/海外(英語文章Bio)"
    # 日本語が無い状態で、タグ+bio全体が英語文章っぽい場合
    if not re.search(r"[ぁ-んァ-ヶ一-龥]", _nj_full) and _nj_english_sentence_like(_nj_full):
        return "外国語/海外(英語文章)"

    # 韓国語は単語タグだけなら許容。長い/文章っぽい場合だけ除外
    _hangul_count = len(re.findall(r"[\uAC00-\uD7AF]", _nj_full))
    _hangul_tokens = re.findall(r"[\uAC00-\uD7AF]{2,}", _nj_full)
    if _hangul_count >= 10 or len(_hangul_tokens) >= 3:
        return "外国語/海外(韓国語文章)"
    if _nj_bio_s and len(re.findall(r"[\uAC00-\uD7AF]", _nj_bio_s)) >= 6:
        return "外国語/海外(韓国語Bio)"


    # 追加除外: 量産タグ/アイドル系/海外音楽系
    try:
        _noise_uid = (
            _get(candidate, "unique_id", None)
            or _get(candidate, "user_id", None)
            or _get(candidate, "id", None)
            or ""
        )
        _noise_name = (
            _get(candidate, "display_name", None)
            or _get(candidate, "nickname", None)
            or _get(candidate, "name", None)
            or ""
        )
        _noise_bio = (
            _get(candidate, "profile_bio", None)
            or _get(candidate, "bio", None)
            or _get(candidate, "signature", None)
            or _get(candidate, "profile_text", None)
            or _get(candidate, "description", None)
            or _get(candidate, "desc", None)
            or ""
        )
        _noise_tags_raw = (
            _get(candidate, "hashtags", None)
            or _get(candidate, "hashtag", None)
            or _get(candidate, "tags", None)
            or _get(candidate, "tag_text", None)
            or _get(candidate, "hashtag_text", None)
            or ""
        )
    except Exception:
        _noise_uid = (
            getattr(candidate, "unique_id", None)
            or getattr(candidate, "user_id", None)
            or getattr(candidate, "id", None)
            or ""
        )
        _noise_name = (
            getattr(candidate, "display_name", None)
            or getattr(candidate, "nickname", None)
            or getattr(candidate, "name", None)
            or ""
        )
        _noise_bio = (
            getattr(candidate, "profile_bio", None)
            or getattr(candidate, "bio", None)
            or getattr(candidate, "signature", None)
            or getattr(candidate, "profile_text", None)
            or getattr(candidate, "description", None)
            or getattr(candidate, "desc", None)
            or ""
        )
        _noise_tags_raw = (
            getattr(candidate, "hashtags", None)
            or getattr(candidate, "hashtag", None)
            or getattr(candidate, "tags", None)
            or getattr(candidate, "tag_text", None)
            or getattr(candidate, "hashtag_text", None)
            or ""
        )

    if isinstance(_noise_tags_raw, (list, tuple, set)):
        _noise_tags = " ".join([str(x) for x in _noise_tags_raw]).strip()
    else:
        _noise_tags = str(_noise_tags_raw or "").strip()

    _noise_uid_s = str(_noise_uid or "").strip().replace("@", "")
    _noise_name_s = str(_noise_name or "").strip()
    _noise_bio_s = str(_noise_bio or "").strip()
    _noise_full = " ".join([_noise_uid_s, _noise_name_s, _noise_tags, _noise_bio_s])
    _noise_full_lower = _noise_full.lower()
    _noise_tags_lower = _noise_tags.lower()

    for _nw in ['daun muda', 'daun', 'muda', '田島櫻子', '田島櫻子ちゃん', 'onephony', 'slipknot', 'metal', "don't like small talk", 'dont like small talk', 'small talk']:
        _nws = str(_nw or "").strip()
        if _nws and _nws.lower() in _noise_full_lower:
            return f"NGワード({_nws})"

    if re.search(r"(?i)(?<![a-z])([a-z])\1{7,}(?![a-z])", _noise_tags):
        return "ハッシュタグNG(同一英字連続)"

    if "fyp" in _noise_tags_lower and re.search(r"(?i)([a-z])\1{5,}", _noise_tags):
        return "ハッシュタグNG(fyp+同一英字連続)"

    _noise_has_japanese = re.search(r"[ぁ-んァ-ヶ一-龥]", _noise_full) is not None
    if not _noise_has_japanese and re.search(r"[a-zA-Z]", _noise_tags) and re.search(r"[a-zA-Z]", _noise_bio_s):
        if len(_noise_bio_s) <= 30:
            return "外国語/海外(英字タグ+短文英字Bio)"

    if _noise_bio_s == "" and ("onephony" in _noise_tags_lower or "田島櫻子" in _noise_tags):
        return "アイドル/ファン系タグ(プロフィール紹介文空欄)"


    # 追加除外: ベトナム系ローマ字タグ/インスタ誘導/短すぎるメンションBio
    try:
        _vn_uid = (
            _get(candidate, "unique_id", None)
            or _get(candidate, "user_id", None)
            or _get(candidate, "id", None)
            or ""
        )
        _vn_name = (
            _get(candidate, "display_name", None)
            or _get(candidate, "nickname", None)
            or _get(candidate, "name", None)
            or ""
        )
        _vn_bio = (
            _get(candidate, "profile_bio", None)
            or _get(candidate, "bio", None)
            or _get(candidate, "signature", None)
            or _get(candidate, "profile_text", None)
            or _get(candidate, "description", None)
            or _get(candidate, "desc", None)
            or ""
        )
        _vn_tags_raw = (
            _get(candidate, "hashtags", None)
            or _get(candidate, "hashtag", None)
            or _get(candidate, "tags", None)
            or _get(candidate, "tag_text", None)
            or _get(candidate, "hashtag_text", None)
            or ""
        )
    except Exception:
        _vn_uid = (
            getattr(candidate, "unique_id", None)
            or getattr(candidate, "user_id", None)
            or getattr(candidate, "id", None)
            or ""
        )
        _vn_name = (
            getattr(candidate, "display_name", None)
            or getattr(candidate, "nickname", None)
            or getattr(candidate, "name", None)
            or ""
        )
        _vn_bio = (
            getattr(candidate, "profile_bio", None)
            or getattr(candidate, "bio", None)
            or getattr(candidate, "signature", None)
            or getattr(candidate, "profile_text", None)
            or getattr(candidate, "description", None)
            or getattr(candidate, "desc", None)
            or ""
        )
        _vn_tags_raw = (
            getattr(candidate, "hashtags", None)
            or getattr(candidate, "hashtag", None)
            or getattr(candidate, "tags", None)
            or getattr(candidate, "tag_text", None)
            or getattr(candidate, "hashtag_text", None)
            or ""
        )

    if isinstance(_vn_tags_raw, (list, tuple, set)):
        _vn_tags = " ".join([str(x) for x in _vn_tags_raw]).strip()
    else:
        _vn_tags = str(_vn_tags_raw or "").strip()

    _vn_uid_s = str(_vn_uid or "").strip().replace("@", "")
    _vn_name_s = str(_vn_name or "").strip()
    _vn_bio_s = str(_vn_bio or "").strip()
    _vn_full = " ".join([_vn_uid_s, _vn_name_s, _vn_tags, _vn_bio_s])
    _vn_full_lower = _vn_full.lower()
    _vn_tags_lower = _vn_tags.lower()
    _vn_bio_lower = _vn_bio_s.lower()

    # ベトナム系/海外ローマ字タグ
    for _w in ['vaycongchua', 'phongcachphap', 'bachnguyetquang', 'stylenangtho', 'nangtho', 'outfitlangman', 'langman', 'vay', 'congchua', 'phongcach', 'bong_iu', 'bongiu', 'hihi']:
        _ws = str(_w or "").strip()
        if _ws and _ws.lower() in _vn_full_lower:
            return f"外国語/海外({_ws})"

    # インスタ/外部SNS誘導
    for _w in ['affiliatemarketing', 'affiliate marketing', 'いんすたきて', 'インスタきて', 'インスタ来て', 'instaきて', 'instagramきて', 'いんすた来て', 'ID→', 'id→', 'ID:', 'id:']:
        _ws = str(_w or "").strip()
        if _ws and _ws.lower() in _vn_full_lower:
            return f"SNS誘導({_ws})"

    # affiliate系
    if "affiliate" in _vn_full_lower:
        return "NGワード(affiliate)"

    # ハッシュタグがfyp込みで、紹介文がインスタID誘導っぽい場合
    if "fyp" in _vn_tags_lower and re.search(r"(いんすた|インスタ|insta|instagram|id\s*[→:：])", _vn_bio_lower):
        return "SNS誘導(fyp+インスタID)"

    # bioが @xx だけ、またはほぼメンションのみで短すぎる場合
    _mention_only = re.fullmatch(r"@?[a-zA-Z0-9_.]{1,20}", _vn_bio_s or "") is not None
    if _mention_only and len(_vn_bio_s.replace("@", "").strip()) <= 4:
        return "プロフィール紹介文が短すぎるメンションのみ"

    # cortisなど、K-POP/海外タグが単体でbio短文の場合
    for _w in ['cortis']:
        _ws = str(_w or "").strip()
        if _ws and _ws.lower() in _vn_tags_lower and len(_vn_bio_s) <= 5:
            return f"海外/ノイズタグ({_ws})"


    # 追加除外: インドネシア語/マレー語系タグ・プロフィール
    try:
        _indo_uid = (
            _get(candidate, "unique_id", None)
            or _get(candidate, "user_id", None)
            or _get(candidate, "id", None)
            or ""
        )
        _indo_name = (
            _get(candidate, "display_name", None)
            or _get(candidate, "nickname", None)
            or _get(candidate, "name", None)
            or ""
        )
        _indo_bio = (
            _get(candidate, "profile_bio", None)
            or _get(candidate, "bio", None)
            or _get(candidate, "signature", None)
            or _get(candidate, "profile_text", None)
            or _get(candidate, "description", None)
            or _get(candidate, "desc", None)
            or ""
        )
        _indo_tags_raw = (
            _get(candidate, "hashtags", None)
            or _get(candidate, "hashtag", None)
            or _get(candidate, "tags", None)
            or _get(candidate, "tag_text", None)
            or _get(candidate, "hashtag_text", None)
            or ""
        )
    except Exception:
        _indo_uid = (
            getattr(candidate, "unique_id", None)
            or getattr(candidate, "user_id", None)
            or getattr(candidate, "id", None)
            or ""
        )
        _indo_name = (
            getattr(candidate, "display_name", None)
            or getattr(candidate, "nickname", None)
            or getattr(candidate, "name", None)
            or ""
        )
        _indo_bio = (
            getattr(candidate, "profile_bio", None)
            or getattr(candidate, "bio", None)
            or getattr(candidate, "signature", None)
            or getattr(candidate, "profile_text", None)
            or getattr(candidate, "description", None)
            or getattr(candidate, "desc", None)
            or ""
        )
        _indo_tags_raw = (
            getattr(candidate, "hashtags", None)
            or getattr(candidate, "hashtag", None)
            or getattr(candidate, "tags", None)
            or getattr(candidate, "tag_text", None)
            or getattr(candidate, "hashtag_text", None)
            or ""
        )

    if isinstance(_indo_tags_raw, (list, tuple, set)):
        _indo_tags = " ".join([str(x) for x in _indo_tags_raw]).strip()
    else:
        _indo_tags = str(_indo_tags_raw or "").strip()

    _indo_full = " ".join([
        str(_indo_uid or ""),
        str(_indo_name or ""),
        _indo_tags,
        str(_indo_bio or "")
    ])
    _indo_full_lower = _indo_full.lower()

    for _iw in ['cewek', 'cewekcantik', 'cewekidaman', 'wanita', 'masih mencari', 'cantik', 'idaman', 'mencari', 'gadis', 'perempuan', 'indonesia', 'jakarta', 'malaysia', 'malay']:
        _iws = str(_iw or "").strip()
        if _iws and _iws.lower() in _indo_full_lower:
            return f"外国語/海外({_iws})"


    # 追加除外: ハッシュタグ08/09 + 配信系
    try:
        _stream_uid = (
            _get(candidate, "unique_id", None)
            or _get(candidate, "user_id", None)
            or _get(candidate, "id", None)
            or ""
        )
        _stream_name = (
            _get(candidate, "display_name", None)
            or _get(candidate, "nickname", None)
            or _get(candidate, "name", None)
            or ""
        )
        _stream_bio = (
            _get(candidate, "profile_bio", None)
            or _get(candidate, "bio", None)
            or _get(candidate, "signature", None)
            or _get(candidate, "profile_text", None)
            or _get(candidate, "description", None)
            or _get(candidate, "desc", None)
            or ""
        )
        _stream_tags_raw = (
            _get(candidate, "hashtags", None)
            or _get(candidate, "hashtag", None)
            or _get(candidate, "tags", None)
            or _get(candidate, "tag_text", None)
            or _get(candidate, "hashtag_text", None)
            or ""
        )
    except Exception:
        _stream_uid = (
            getattr(candidate, "unique_id", None)
            or getattr(candidate, "user_id", None)
            or getattr(candidate, "id", None)
            or ""
        )
        _stream_name = (
            getattr(candidate, "display_name", None)
            or getattr(candidate, "nickname", None)
            or getattr(candidate, "name", None)
            or ""
        )
        _stream_bio = (
            getattr(candidate, "profile_bio", None)
            or getattr(candidate, "bio", None)
            or getattr(candidate, "signature", None)
            or getattr(candidate, "profile_text", None)
            or getattr(candidate, "description", None)
            or getattr(candidate, "desc", None)
            or ""
        )
        _stream_tags_raw = (
            getattr(candidate, "hashtags", None)
            or getattr(candidate, "hashtag", None)
            or getattr(candidate, "tags", None)
            or getattr(candidate, "tag_text", None)
            or getattr(candidate, "hashtag_text", None)
            or ""
        )

    if isinstance(_stream_tags_raw, (list, tuple, set)):
        _stream_tags = " ".join([str(x) for x in _stream_tags_raw]).strip()
    else:
        _stream_tags = str(_stream_tags_raw or "").strip()

    _stream_full = " ".join([
        str(_stream_uid or ""),
        str(_stream_name or ""),
        _stream_tags,
        str(_stream_bio or "")
    ])
    _stream_full_lower = _stream_full.lower()

    for _sw in ['配信', 'ｻﾌﾞ配信', 'サブ配信', '配信専用', 'テキーラ配信', '本垢', '本アカ', '本アカウント', '他にもあります']:
        _sws = str(_sw or "").strip()
        if _sws and _sws.lower() in _stream_full_lower:
            return f"NGワード({_sws})"

    # ハッシュタグに 08 / 09 が単体で含まれる場合は除外
    _tags_norm_digits = _stream_tags.translate(str.maketrans("０１２３４５６７８９", "0123456789"))
    _tag_tokens = [t for t in re.split(r"[#＃\s,，、/／｜|・.．。:_\-－ー]+", _tags_norm_digits) if t]
    if "08" in _tag_tokens:
        return "ハッシュタグNG(08)"
    if "09" in _tag_tokens:
        return "ハッシュタグNG(09)"


    # 追加除外: 外国文字/着替えフェチ/shit/絵文字のみBio
    try:
        _extra_uid = (
            _get(candidate, "unique_id", None)
            or _get(candidate, "user_id", None)
            or _get(candidate, "id", None)
            or ""
        )
        _extra_name = (
            _get(candidate, "display_name", None)
            or _get(candidate, "nickname", None)
            or _get(candidate, "name", None)
            or ""
        )
        _extra_bio = (
            _get(candidate, "profile_bio", None)
            or _get(candidate, "bio", None)
            or _get(candidate, "signature", None)
            or _get(candidate, "profile_text", None)
            or _get(candidate, "description", None)
            or _get(candidate, "desc", None)
            or ""
        )
        _extra_tags_raw = (
            _get(candidate, "hashtags", None)
            or _get(candidate, "hashtag", None)
            or _get(candidate, "tags", None)
            or _get(candidate, "tag_text", None)
            or _get(candidate, "hashtag_text", None)
            or ""
        )
    except Exception:
        _extra_uid = (
            getattr(candidate, "unique_id", None)
            or getattr(candidate, "user_id", None)
            or getattr(candidate, "id", None)
            or ""
        )
        _extra_name = (
            getattr(candidate, "display_name", None)
            or getattr(candidate, "nickname", None)
            or getattr(candidate, "name", None)
            or ""
        )
        _extra_bio = (
            getattr(candidate, "profile_bio", None)
            or getattr(candidate, "bio", None)
            or getattr(candidate, "signature", None)
            or getattr(candidate, "profile_text", None)
            or getattr(candidate, "description", None)
            or getattr(candidate, "desc", None)
            or ""
        )
        _extra_tags_raw = (
            getattr(candidate, "hashtags", None)
            or getattr(candidate, "hashtag", None)
            or getattr(candidate, "tags", None)
            or getattr(candidate, "tag_text", None)
            or getattr(candidate, "hashtag_text", None)
            or ""
        )

    if isinstance(_extra_tags_raw, (list, tuple, set)):
        _extra_tags = " ".join([str(x) for x in _extra_tags_raw]).strip()
    else:
        _extra_tags = str(_extra_tags_raw or "").strip()

    _extra_uid_s = str(_extra_uid or "").strip().replace("@", "")
    _extra_name_s = str(_extra_name or "").strip()
    _extra_bio_s = str(_extra_bio or "").strip()
    _extra_full = " ".join([_extra_uid_s, _extra_name_s, _extra_tags, _extra_bio_s])
    _extra_full_lower = _extra_full.lower()

    for _w in ['shit', 'お着替え', '着替え', '着替えチャレンジ', 'フェチ', 'fetish', 'ミニサイズ', 'パレオ']:
        _ws = str(_w or "").strip()
        if _ws and _ws.lower() in _extra_full_lower:
            return f"NGワード({_ws})"

    # ミャンマー語/クメール語/ラオ語など、これまで漏れていた外国文字
    if any(
        (0x1000 <= ord(_ch) <= 0x109F)
        or (0x1780 <= ord(_ch) <= 0x17FF)
        or (0x0E80 <= ord(_ch) <= 0x0EFF)
        for _ch in _extra_full
    ):
        return "外国語/海外(東南アジア系文字)"

    # bioが絵文字・記号だけで、ハッシュタグが英字/ランダム寄りの場合は除外
    if _extra_bio_s:
        _bio_has_meaning_text = re.search(r"[a-zA-Z0-9ぁ-んァ-ヶ一-龥]", _extra_bio_s) is not None
        _bio_is_emoji_only = not _bio_has_meaning_text
        _tags_has_ascii = re.search(r"[a-zA-Z]", _extra_tags) is not None
        _tags_has_japanese = re.search(r"[ぁ-んァ-ヶ一-龥]", _extra_tags) is not None
        if _bio_is_emoji_only and _tags_has_ascii and not _tags_has_japanese:
            return "プロフィール紹介文が絵文字のみ/英字タグ"


    # 類似アカウント除外v1: 1〜5 ※follow/いいね稼ぎ系は未実装
    try:
        _sim_uid = (
            _get(candidate, "unique_id", None)
            or _get(candidate, "user_id", None)
            or _get(candidate, "id", None)
            or ""
        )
        _sim_name = (
            _get(candidate, "display_name", None)
            or _get(candidate, "nickname", None)
            or _get(candidate, "name", None)
            or ""
        )
        _sim_bio = (
            _get(candidate, "profile_bio", None)
            or _get(candidate, "bio", None)
            or _get(candidate, "signature", None)
            or _get(candidate, "profile_text", None)
            or _get(candidate, "description", None)
            or _get(candidate, "desc", None)
            or ""
        )
        _sim_tags_raw = (
            _get(candidate, "hashtags", None)
            or _get(candidate, "hashtag", None)
            or _get(candidate, "tags", None)
            or _get(candidate, "tag_text", None)
            or _get(candidate, "hashtag_text", None)
            or ""
        )
    except Exception:
        _sim_uid = (
            getattr(candidate, "unique_id", None)
            or getattr(candidate, "user_id", None)
            or getattr(candidate, "id", None)
            or ""
        )
        _sim_name = (
            getattr(candidate, "display_name", None)
            or getattr(candidate, "nickname", None)
            or getattr(candidate, "name", None)
            or ""
        )
        _sim_bio = (
            getattr(candidate, "profile_bio", None)
            or getattr(candidate, "bio", None)
            or getattr(candidate, "signature", None)
            or getattr(candidate, "profile_text", None)
            or getattr(candidate, "description", None)
            or getattr(candidate, "desc", None)
            or ""
        )
        _sim_tags_raw = (
            getattr(candidate, "hashtags", None)
            or getattr(candidate, "hashtag", None)
            or getattr(candidate, "tags", None)
            or getattr(candidate, "tag_text", None)
            or getattr(candidate, "hashtag_text", None)
            or ""
        )

    if isinstance(_sim_tags_raw, (list, tuple, set)):
        _sim_tags = " ".join([str(x) for x in _sim_tags_raw]).strip()
    else:
        _sim_tags = str(_sim_tags_raw or "").strip()

    _sim_uid_s = str(_sim_uid or "").strip().replace("@", "")
    _sim_name_s = str(_sim_name or "").strip()
    _sim_bio_s = str(_sim_bio or "").strip()
    _sim_full = " ".join([_sim_uid_s, _sim_name_s, _sim_tags, _sim_bio_s])
    _sim_full_lower = _sim_full.lower()

    # 3. 外部リンク誘導系。ただし litlink / lit.link は除外しない
    _sim_has_litlink = ("lit.link" in _sim_full_lower) or ("litlink" in _sim_full_lower)
    for _link_ng in ['facebook.com', 'mibextid', 'onlyfans', 'ofans', 'fansly']:
        if _link_ng in _sim_full_lower and not _sim_has_litlink:
            return f"外部リンクNG({_link_ng})"

    # 4. 美容・色気・成人・下着・成熟系
    for _adult_w in ['lingerie', 'gorgeous', 'mature', 'maturewoman', 'maturewomen', '成熟', '成熟した女性', '色気', 'セクシー', 'sexy', '大人', '大人女子', '大人ガーリー', 'big.ass', 'ass9855', 'MagneticBeauty', 'SelfLoveVibes', 'GlamAndGrow', 'ConfidenceIsKey', 'beauty', 'glam']:
        _adult_s = str(_adult_w or "").strip()
        if not _adult_s:
            continue
        if _adult_s.lower() == "beauty":
            if "beauty" in _sim_full_lower and (_sim_bio_s == "" or re.search(r"[a-zA-Z]", _sim_tags)):
                return "NGワード(beauty系)"
            continue
        if _adult_s.lower() in _sim_full_lower:
            return f"NGワード({_adult_s})"

    # 5. コスプレ・アニメ・キャラ・ゲーム系
    for _cg_w in ['cosplay', 'cosplayer', 'コスプレ', 'レイヤー', '宝鐘マリン', 'ホロライブ', 'hololive', 'アスカ', 'asuka', 'neongenesisevangelion', 'evangelion', 'エヴァ', 'エヴァンゲリオン', 'fivem', 'gta', 'gtarp', 'ゲーム実況', 'gaming']:
        _cg_s = str(_cg_w or "").strip()
        if _cg_s and _cg_s.lower() in _sim_full_lower:
            return f"NGワード({_cg_s})"

    # 1. プロフ空欄 + 英字ハッシュタグのみ
    if _sim_bio_s == "" and _sim_tags:
        _sim_has_japanese_tag = re.search(r"[ぁ-んァ-ヶ一-龥]", _sim_tags) is not None
        _sim_has_ascii_tag = re.search(r"[a-zA-Z]", _sim_tags) is not None
        if _sim_has_ascii_tag and not _sim_has_japanese_tag:
            return "外国語/海外(英字タグのみ/プロフィール紹介文空欄)"

    # 2. プロフ空欄 + ランダムIDっぽいユーザーID
    _sim_uid_clean = re.sub(r"[^a-zA-Z0-9]", "", _sim_uid_s).lower()
    _sim_uid_has_letter = re.search(r"[a-z]", _sim_uid_clean) is not None
    _sim_uid_has_digit = re.search(r"[0-9]", _sim_uid_clean) is not None
    _sim_uid_has_sep = ("_" in _sim_uid_s) or ("." in _sim_uid_s) or ("-" in _sim_uid_s)
    _sim_uid_random_like = (
        _sim_bio_s == ""
        and len(_sim_uid_clean) >= 6
        and _sim_uid_has_letter
        and _sim_uid_has_digit
        and not _sim_uid_has_sep
    )
    if _sim_uid_random_like:
        return "ランダムID/プロフィール紹介文空欄"


    # 1539行目以降の色付きアカウントID除外
    _colored_excluded_ids_1539 = ['erishinn', 'layna0930', 'olehistrinya43', 'kata_kata_hati_yo', 'nasyacuw3k', 'una____1116', 'uutkyds2189166932', '5dfgegd', 'zella_matcha']
    try:
        _candidate_uid_1539 = (
            _get(candidate, "unique_id", None)
            or _get(candidate, "user_id", None)
            or _get(candidate, "id", None)
            or ""
        )
    except Exception:
        _candidate_uid_1539 = (
            getattr(candidate, "unique_id", None)
            or getattr(candidate, "user_id", None)
            or getattr(candidate, "id", None)
            or ""
        )
    _candidate_uid_1539 = str(_candidate_uid_1539 or "").strip().replace("@", "")
    if _candidate_uid_1539 in _colored_excluded_ids_1539:
        return f"色付き除外ID({_candidate_uid_1539})"


    # 色付き漏れ行対策v2: 追加NG/海外/スパム系ワード ※litlinkは除外しない
    _colored_leak_ng_words_v2 = ['Doublefedora', 'mafioso', 'forsaken', 'ベトナムフェスティバル', 'ウエノデコリアンフェスタ', 'コリアンフェスタ', 'カリブラテンアメリカストリート', 'ラテンアメリカ', '日比谷音楽祭', 'アウトドアシネマ', 'スタンダップコメディ', 'standupcomedy', 'crowdwork', 'ほんまやでダンス', 'newmusic', 'いいねください', 'fypツ', 'smail', 'facebook.com', 'mibextid', '可愛い女の子', '毎日 可愛い女の子', '宝鐘マリン', 'くださいませチャレンジ', '愛くださいませ', '成熟した女性', '成熟', 'cosplay', 'cosplayer', 'neongenesisevangelion', 'アスカ', 'lingerie', 'gorgeous', 'MagneticBeauty', 'SelfLoveVibes', 'GlamAndGrow', 'ConfidenceIsKey', 'PR エバーカラー', 'エバーカラー', 'カラコン', 'ROWfreelove', 'rowlove', 'rowbuzz', 'charlesandsylvia', 'wolfieandsylvia', 'couplescomedy', 'じゅんな', 'ゆうな']
    _colored_leak_text_lower_v2 = text.lower()
    _has_litlink_v2 = ("lit.link" in _colored_leak_text_lower_v2) or ("litlink" in _colored_leak_text_lower_v2)

    for _colored_ng in _colored_leak_ng_words_v2:
        _colored_ng_s = str(_colored_ng or "").strip()
        if not _colored_ng_s:
            continue
        if _colored_ng_s.lower() in ["litlink", "lit.link"]:
            continue
        if _colored_ng_s.lower() in _colored_leak_text_lower_v2:
            return f"NGワード({_colored_ng_s})"

    for _link_ng in ["facebook.com", "mibextid", "onlyfans", "ofans", "fansly"]:
        if _link_ng in _colored_leak_text_lower_v2 and not _has_litlink_v2:
            return f"外部リンクNG({_link_ng})"

    try:
        _colored_bio = (
            _get(candidate, "profile_bio", None)
            or _get(candidate, "bio", None)
            or _get(candidate, "signature", None)
            or _get(candidate, "profile_text", None)
            or _get(candidate, "description", None)
            or _get(candidate, "desc", None)
            or ""
        )
        _colored_tags_raw = (
            _get(candidate, "hashtags", None)
            or _get(candidate, "hashtag", None)
            or _get(candidate, "tags", None)
            or _get(candidate, "tag_text", None)
            or _get(candidate, "hashtag_text", None)
            or ""
        )
    except Exception:
        _colored_bio = (
            getattr(candidate, "profile_bio", None)
            or getattr(candidate, "bio", None)
            or getattr(candidate, "signature", None)
            or getattr(candidate, "profile_text", None)
            or getattr(candidate, "description", None)
            or getattr(candidate, "desc", None)
            or ""
        )
        _colored_tags_raw = (
            getattr(candidate, "hashtags", None)
            or getattr(candidate, "hashtag", None)
            or getattr(candidate, "tags", None)
            or getattr(candidate, "tag_text", None)
            or getattr(candidate, "hashtag_text", None)
            or ""
        )

    if isinstance(_colored_tags_raw, (list, tuple, set)):
        _colored_tags = " ".join([str(x) for x in _colored_tags_raw]).strip()
    else:
        _colored_tags = str(_colored_tags_raw or "").strip()

    _colored_tags_lower = _colored_tags.lower()
    _colored_bio_s = str(_colored_bio or "").strip()

    if _colored_bio_s == "" and _colored_tags:
        _has_japanese = re.search(r"[ぁ-んァ-ヶ一-龥]", _colored_tags) is not None
        _has_ascii_letter = re.search(r"[a-zA-Z]", _colored_tags) is not None
        if _has_ascii_letter and not _has_japanese:
            return "外国語/海外(英字タグのみ/プロフィール紹介文空欄)"

    if _colored_bio_s == "" and "fyp" in _colored_tags_lower:
        return "プロフィール紹介文空欄(fyp)"

    if _colored_bio_s == "" and _colored_tags.strip() in ["可愛", "可愛い"]:
        return "ハッシュタグ単体NG(可愛)"

    if "可愛い" in _colored_tags and "女の子" in _colored_tags:
        return "ハッシュタグNG(可愛い女の子)"


    # 色付き漏れ行対策: 追加NG/海外/スパム系ワード
    _colored_leak_ng_words = ['Doublefedora', 'mafioso', 'forsaken', 'ベトナムフェスティバル', 'ウエノデコリアンフェスタ', 'コリアンフェスタ', 'カリブラテンアメリカストリート', 'ラテンアメリカ', '日比谷音楽祭', 'アウトドアシネマ', 'スタンダップコメディ', 'standupcomedy', 'crowdwork', 'ほんまやでダンス', 'newmusic', 'いいねください', 'fypツ', 'smail', 'facebook.com', 'mibextid', '可愛い女の子', '毎日 可愛い女の子', '宝鐘マリン', 'くださいませチャレンジ', '愛くださいませ', '成熟した女性', '成熟', 'cosplay', 'cosplayer', 'neongenesisevangelion', 'アスカ', 'lingerie', 'gorgeous', 'MagneticBeauty', 'SelfLoveVibes', 'GlamAndGrow', 'ConfidenceIsKey', 'PR エバーカラー', 'エバーカラー', 'カラコン', 'ROWfreelove', 'rowlove', 'rowbuzz', 'charlesandsylvia', 'wolfieandsylvia', 'couplescomedy', 'じゅんな', 'ゆうな']
    _colored_leak_text_lower = text.lower()
    for _colored_ng in _colored_leak_ng_words:
        _colored_ng_s = str(_colored_ng or "").strip()
        if _colored_ng_s and _colored_ng_s.lower() in _colored_leak_text_lower:
            return f"NGワード({_colored_ng_s})"

    # 色付き漏れ行対策: プロフ空欄 + 英字ハッシュタグのみ/ほぼ海外タグ
    try:
        _colored_bio = (
            _get(candidate, "profile_bio", None)
            or _get(candidate, "bio", None)
            or _get(candidate, "signature", None)
            or _get(candidate, "profile_text", None)
            or _get(candidate, "description", None)
            or _get(candidate, "desc", None)
            or ""
        )
        _colored_tags_raw = (
            _get(candidate, "hashtags", None)
            or _get(candidate, "hashtag", None)
            or _get(candidate, "tags", None)
            or _get(candidate, "tag_text", None)
            or _get(candidate, "hashtag_text", None)
            or ""
        )
    except Exception:
        _colored_bio = (
            getattr(candidate, "profile_bio", None)
            or getattr(candidate, "bio", None)
            or getattr(candidate, "signature", None)
            or getattr(candidate, "profile_text", None)
            or getattr(candidate, "description", None)
            or getattr(candidate, "desc", None)
            or ""
        )
        _colored_tags_raw = (
            getattr(candidate, "hashtags", None)
            or getattr(candidate, "hashtag", None)
            or getattr(candidate, "tags", None)
            or getattr(candidate, "tag_text", None)
            or getattr(candidate, "hashtag_text", None)
            or ""
        )

    if isinstance(_colored_tags_raw, (list, tuple, set)):
        _colored_tags = " ".join([str(x) for x in _colored_tags_raw]).strip()
    else:
        _colored_tags = str(_colored_tags_raw or "").strip()

    _colored_tags_lower = _colored_tags.lower()
    _colored_bio_s = str(_colored_bio or "").strip()

    if _colored_bio_s == "" and _colored_tags:
        _has_japanese = re.search(r"[ぁ-んァ-ヶ一-龥]", _colored_tags) is not None
        _has_ascii_letter = re.search(r"[a-zA-Z]", _colored_tags) is not None
        if _has_ascii_letter and not _has_japanese:
            return "外国語/海外(英字タグのみ/プロフィール紹介文空欄)"

    if _colored_bio_s == "" and "fyp" in _colored_tags_lower:
        return "プロフィール紹介文空欄(fyp)"

    if _colored_bio_s == "" and _colored_tags.strip() in ["可愛", "可愛い"]:
        return "ハッシュタグ単体NG(可愛)"

    if "可愛い" in _colored_tags and "女の子" in _colored_tags:
        return "ハッシュタグNG(可愛い女の子)"


    # V5共有前保証: 海外/外国語アカウント除外
    _v5_foreign_text = text.lower()
    _v5_foreign_keywords = [
        "taiwan", "taipei", "台灣", "台湾", "臺灣", "香港", "hong kong", "hongkong",
        "china", "chinese", "中文", "繁體", "繁体", "中国語", "華語", "华语",
        "korea", "korean", "한국", "태국", "thai", "thailand", "philippines", "vietnam",
        "indonesia", "malaysia", "singapore", "overseas", "foreign", "foreigner",
        "xuhuong", "xuhuongtiktok", "xu huong", "xuhướng", "hướng",
        "gaixinh", "gaixinhtiktok", "gai xinh", "xinhdep", "xinh dep",
        "girlxinh", "nhactrung", "dungmai", "halinh",
        "babygirl", "bikini", "binkini",
        "viral", "trending", "foryou", "hottrend",
        "follow mình", "flow em", "follow tui", "mọi người", "giúp mình",
        "lên 1000fl", "1000fl", "vào đây", "tìm gì", "em rất", "cô đơn",
        "mình", "nhé", "nhá", "đi ạ", "tui",
        "置顶找我", "gaixinhmacbinkini",
        "australia", "perth", "single", "makefriends", "southern hemisphere", "freedom",
        "手势舞", "甜妹", "白羊座"
    ]
    for _kw in _v5_foreign_keywords:
        if _kw.lower() in _v5_foreign_text or _kw in text:
            return f"外国語/海外({_kw})"

    if re.search(r"[\uac00-\ud7af\u0e00-\u0e7f\u0400-\u04ff\u0600-\u06ff]", text):
        return "外国語/海外(文字種)"

    if re.search(r"[ăâêôơưđàáạảãằắặẳẵầấậẩẫèéẹẻẽềếệểễìíịỉĩòóọỏõồốộổỗờớợởỡùúụủũừứựửữỳýỵỷỹ]", _v5_foreign_text):
        return "外国語/海外(ベトナム語文字)"

    _v5_chinese_spam_keywords = [
        "置顶", "找我", "美女", "漂亮", "可爱", "关注", "私信", "主页", "點", "點擊", "點我",
        "視頻", "视频", "比基尼", "泳裝", "泳装"
    ]
    for _kw in _v5_chinese_spam_keywords:
        if _kw in text:
            return f"外国語/海外({_kw})"

    _v5_traditional_chars = "這裡妳們嗎沒麼個幾為點歡樂國學廣東臺灣說聽買賣開網寫氣體應覺讓從與給還發"
    if sum(1 for _ch in text if _ch in _v5_traditional_chars) >= 2:
        return "外国語/海外(繁体字)"


    # 追加NGワード: teamwork
    if "teamwork" in text.lower():
        return "NGワード(teamwork)"


    # 追加NGワード: tiktok / 踊る / 極愛パラドックス / ラブパラ / 大人ガーリー / アラフィフ
    _extra_ng_text_lower = text.lower()
    for _extra_ng in ["踊る", "極愛パラドックス", "ラブパラ", "大人ガーリー", "アラフィフ"]:
        if _extra_ng in text:
            return f"NGワード({_extra_ng})"

    # ハッシュタグ3点セット除外: 美人 + モデル + かわいい
    try:
        _combo_hashtags_raw = (
            _get(candidate, "hashtags", None)
            or _get(candidate, "hashtag", None)
            or _get(candidate, "tags", None)
            or _get(candidate, "tag_text", None)
            or _get(candidate, "hashtag_text", None)
            or ""
        )
    except Exception:
        _combo_hashtags_raw = (
            getattr(candidate, "hashtags", None)
            or getattr(candidate, "hashtag", None)
            or getattr(candidate, "tags", None)
            or getattr(candidate, "tag_text", None)
            or getattr(candidate, "hashtag_text", None)
            or ""
        )
    if isinstance(_combo_hashtags_raw, (list, tuple, set)):
        _combo_hashtags_text = " ".join([str(x) for x in _combo_hashtags_raw])
    else:
        _combo_hashtags_text = str(_combo_hashtags_raw or "")
    if all(_kw in _combo_hashtags_text for _kw in ["美人", "モデル", "かわいい"]):
        return "ハッシュタグNG(美人/モデル/かわいい)"


    # 追加NGワード: 男の娘 / 偽娘 / 女装男子 / ニューハーフ
    for _extra_ng in ["男の娘", "偽娘", "女装男子", "ニューハーフ"]:
        if _extra_ng in text:
            return f"NGワード({_extra_ng})"


    # 追加NGワード: サブスク / 彼氏募集 / 彼氏募集中 / followme / follow me
    _extra_ng_text_lower = text.lower()
    for _extra_ng in ["サブスク", "彼氏募集", "彼氏募集中"]:
        if _extra_ng in text:
            return f"NGワード({_extra_ng})"
    for _extra_ng in ["followme", "follow me"]:
        if _extra_ng in _extra_ng_text_lower:
            return f"NGワード({_extra_ng})"


    # 追加NGワード: fypシ / foryou / 4u / yah / 料理動画 / 料理
    _extra_ng_text_lower = text.lower()
    for _extra_ng in ["fypシ", "foryou", "4u", "yah"]:
        if _extra_ng.lower() in _extra_ng_text_lower:
            return f"NGワード({_extra_ng})"
    for _extra_ng in ["料理動画", "料理"]:
        if _extra_ng in text:
            return f"NGワード({_extra_ng})"


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


    # フォロワー数が取れていない場合は、おすすめに入れない。
    # runner側でこの理由を検知したらリロードする。
    try:
        fc_required = _get(candidate, "follower_count", "")
    except Exception:
        fc_required = getattr(candidate, "follower_count", "")
    if fc_required is None or str(fc_required).strip() == "":
        return "フォロワー数未取得"


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
