"""rules.py 全体で使うヘルパ関数と Sheets プロバイダ状態の集約。

cfull の DI 引数を持っていた account_meta_basic / follower_ad_official /
age_foreign_agency / category_keywords がここから直接 import して使う。
rules.py 本体も同じものを再 export して、後方互換 API
(rules.set_ng_keyword_provider / rules.set_ng_keyword_meta_provider など)を
保つ。

含めるもの:
  - _get, _norm, _candidate_text, _contains_any
  - _load_extra_words(_ng_keyword_provider モジュールグローバルに依存)
  - _foreign_score, _looks_like_foreign, _age_ng, _verified_flag
  - _ng_keyword_provider / _ng_keyword_meta_provider のグローバル状態
  - set_ng_keyword_provider / set_ng_keyword_meta_provider
  - _check_scoped_ng_words
"""
from __future__ import annotations

import re
from typing import Callable, Optional


# ─────────────────────────────────────────────────────────────────────────
# Sheets プロバイダ状態
# ─────────────────────────────────────────────────────────────────────────

_ng_keyword_provider: Optional[Callable[[str], list[str]]] = None
_ng_keyword_meta_provider: Optional[Callable[[str], list[dict]]] = None
_yellow_excluded_provider: Optional[Callable[[], frozenset]] = None

# Sheets「NGワード」タブで 1 文字エントリ(`i`, `a`, `o` 等)が登録されると、
# 部分一致判定が事実上 free-pass で全候補にヒットする(過去 186 件 `NGワード(i)`)。
# 安全弁として 1 文字エントリは無効化して、1 セッション 1 度だけ警告を出す。
_NG_TOO_SHORT_WARNED: set[str] = set()


def _is_too_short_ng_word(word: str) -> bool:
    """部分一致 NG 判定で危険なほど短いワードかどうか。
    現状は「strip 後 1 文字以下」を弾く(英字/かな/数字とも)。"""
    return len(str(word or "").strip()) <= 1


def _warn_too_short_ng_word(word: str, source: str) -> None:
    """1 文字エントリ検出時に 1 度だけ標準出力に警告。
    複数経路から呼ばれても、同じ word は 1 度だけ。"""
    key = f"{source}:{word}"
    if key in _NG_TOO_SHORT_WARNED:
        return
    _NG_TOO_SHORT_WARNED.add(key)
    print(
        f"[NG_WORD_TOO_SHORT_IGNORED] word={word!r} source={source} "
        f"(Sheets「NGワード」タブの 1 文字エントリは部分一致で全候補にヒットするため無効化)",
        flush=True,
    )


def set_ng_keyword_provider(provider: Optional[Callable[[str], list[str]]]) -> None:
    global _ng_keyword_provider
    _ng_keyword_provider = provider


def set_ng_keyword_meta_provider(provider: Optional[Callable[[str], list[dict]]]) -> None:
    """Sheets 由来のメタ付き NG ワード(scope / bio_empty_required)を供給するフック。
    set_ng_keyword_provider と独立で、両方登録できる。未登録なら scoped 判定は無効。"""
    global _ng_keyword_meta_provider
    _ng_keyword_meta_provider = provider


def set_yellow_excluded_provider(provider: Optional[Callable[[], frozenset]]) -> None:
    """Sheets の黄色セル除外 UID セットを供給するフック。
    main.py が sheets.get_yellow_excluded_uids を渡す。未登録なら黄色除外は無効。"""
    global _yellow_excluded_provider
    _yellow_excluded_provider = provider


def _check_yellow_excluded(uid: str) -> Optional[str]:
    """uid が黄色除外セットに含まれていれば reason 文字列を返す。含まれていなければ None。"""
    if _yellow_excluded_provider is None:
        return None
    try:
        ids = _yellow_excluded_provider()
        if uid and uid in ids:
            return f"黄色除外ID({uid})"
    except Exception:
        pass
    return None


# ─────────────────────────────────────────────────────────────────────────
# 基本ヘルパ
# ─────────────────────────────────────────────────────────────────────────


def _get(obj, name, default=None):
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _norm(s) -> str:
    if s is None:
        return ""
    return str(s).lower().replace("　", " ").strip()


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


def _load_extra_words(rules, key: str) -> list:
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
            short_key = key[:-9] if key.endswith("_keywords") else key
            sheet_words = list(_ng_keyword_provider(short_key) or [])
            if short_key == "ng":
                sheet_words = sheet_words + list(_ng_keyword_provider("general") or [])
        except Exception:
            sheet_words = []

    # 1 文字エントリ(`i` 等)は部分一致で全候補にヒットするので Sheets 側からは除外。
    # YAML 側は人手で管理されている前提で素通し。
    filtered_sheet: list = []
    for w in sheet_words:
        if _is_too_short_ng_word(w):
            _warn_too_short_ng_word(str(w), source=f"load_extra_words:{key}")
            continue
        filtered_sheet.append(w)

    return yaml_words + filtered_sheet


def _foreign_score(text: str) -> int:
    # 日本語の漢字は除外。ハングル/タイ語/ロシア語/ネパール語/クメール語/アラビア語などを検出
    patterns = [
        r"[가-힯]",          # Hangul
        r"[฀-๿]",          # Thai
        r"[Ѐ-ӿ]",          # Cyrillic
        r"[ऀ-ॿ]",          # Devanagari
        r"[ក-៿]",          # Khmer
        r"[؀-ۿ]",          # Arabic
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
    # 「200X年生まれ」短縮形(2桁): 09-16 → 2009-2016 born = 2026 時点で 10-17 歳 (未成年) → NG
    # 01-08 は 2001-2008 born = 18-25 歳 (成人) なので NG にしない。
    patterns = [
        "#09", "#10", "#11", "#12", "#13", "#14", "#15", "#16",
        "09line", "10line", "11line", "12line", "13line", "14line", "15line", "16line",
        "09世代", "10世代", "11世代", "12世代", "13世代", "14世代", "15世代", "16世代",
        "fjk", "sjk", "ljk", "jk", "jc", "js",
        "高校生", "中学生", "受験生", "通信制高校",
        "17歳", "16歳", "15歳", "14歳", "13歳",
        # 2009-2016 born = 未成年 → NG。2008 は 18 歳なので NG にしない。
        "2009", "2010", "2011", "2012", "2013", "2014", "2015", "2016",
        "中一", "中二", "中三",
        "中1", "中2", "中3",
        "中学一年", "中学二年", "中学三年",
        "中学1年", "中学2年", "中学3年",
        "中学1年生", "中学2年生", "中学3年生",
        # 高校1-2年は 15-17 歳。高3は18歳に届く可能性ありで除外しない。
        "高一", "高二",
        "高1", "高2",
        "高校一年", "高校二年",
        "高校1年", "高校2年",
        "高校一年生", "高校二年生",
        "高校1年生", "高校2年生",
        # 小学生(6-12 歳)
        "小学生",
        "小一", "小二", "小三", "小四", "小五", "小六",
        "小1", "小2", "小3", "小4", "小5", "小6",
        "小学一年", "小学二年", "小学三年", "小学四年", "小学五年", "小学六年",
        "小学1年", "小学2年", "小学3年", "小学4年", "小学5年", "小学6年",
        "小学一年生", "小学二年生", "小学三年生", "小学四年生", "小学五年生", "小学六年生",
        "小学1年生", "小学2年生", "小学3年生", "小学4年生", "小学5年生", "小学6年生",
        # 「09年生まれ」短縮 → 2009-2016 born = 未成年。01-08 は対象外。
        "09年生まれ", "10年生まれ", "11年生まれ", "12年生まれ",
        "13年生まれ", "14年生まれ", "15年生まれ", "16年生まれ",
        "2009年生まれ", "2010年生まれ", "2011年生まれ", "2012年生まれ",
        "2013年生まれ", "2014年生まれ", "2015年生まれ", "2016年生まれ",
        # 「09年」短縮形(=2009 生まれ)。10-16 は「○年住んでる」等の期間表現で
        # 誤爆する余地があるが、ユーザー方針で全部 NG に倒す。
        "09年", "10年", "11年", "12年", "13年", "14年", "15年", "16年",
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


# ─────────────────────────────────────────────────────────────────────────
# Sheets メタプロバイダによる scoped NG ワード判定
# ─────────────────────────────────────────────────────────────────────────


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
        # 1 文字エントリは部分一致で全候補にヒットするので無効化(安全弁)。
        if _is_too_short_ng_word(word):
            _warn_too_short_ng_word(word, source=f"scoped_ng:{category}")
            continue
        if entry.get("bio_empty_required") and not bio_is_empty:
            continue
        scope = str(entry.get("scope", "all") or "all").lower()
        word_l = word.lower()
        # 短い英数字エントリ(`to`, `and`, `inc`, `pr` 等)は単語境界マッチ。
        # raw substring だと `tokyo`, `tomorrow`, `landscape`, `andrea` 等で大量誤検知する。
        # 単語の前後が英数字でなければヒット扱い(`_contains_any` と同じロジック)。
        use_word_boundary = bool(re.fullmatch(r"[a-z0-9]{2,4}", word_l))
        if use_word_boundary:
            pattern = rf"(?<![a-z0-9]){re.escape(word_l)}(?![a-z0-9])"
            if scope == "hashtag":
                hit = bool(re.search(pattern, hashtags_lower))
            elif scope == "bio":
                hit = bool(re.search(pattern, bio_lower))
            else:  # all
                hit = bool(re.search(pattern, full_text))
        else:
            if scope == "hashtag":
                hit = word_l in hashtags_lower
            elif scope == "bio":
                hit = word_l in bio_lower
            else:  # all
                hit = word_l in full_text
        if hit:
            return f"NGワード({word})"
    return None
