"""汎用 色付き除外 v2 — 9 サブチェック(A〜I)を順番に回す。

共有シート上で色付きマークされたアカウントの傾向を分析して逆引きで作られた
「ぱっと見の類似指標」を、複数次元で連続判定する汎用パッチ v2 ブロック。

サブチェック順(A→I)。判定順は厳守:

  A 明示NG    : 29 語のハードコードリストに含まれる → 「類似除外({word})」
  B 未成年    : ハッシュタグトークン "08"/"09" 単独 → 「ハッシュタグNG({…})」
                43 語の未成年系ワード → 「未成年系NG({word})」
                10〜17 + 歳/才/さい の正規表現 → 「未成年系NG(年齢表記)」
  C 外部リンク: facebook.com / mibextid / onlyfans / fansly / beacons.ai / linktr.ee
                ただし lit.link / litlink は除外しない → 「外部リンクNG({…})」
  D ランダムID: ASCII 英数字 7文字以上+letters+digits+セパレータなし、
                日本語かなが薄い or bio 空 or 英字タグありなら
                「ランダムID/海外・量産寄り」
  E 英字タグ中心: ASCII 英字タグあり + 日本語なし + bio 空/30字以下
                → 「外国語/海外(英字タグ中心+日本語なし)」
  F fyp+薄い  : fyp + かななし + (bio 空 or 英字bio or 中文bio)
                → 「外国語/海外(fyp+日本語要素薄い)」
  G 中国語   : 20 個の中国語フレーズに含まれる → 「外国語/海外(中国語:{phrase})」
                簡体字に 2 つ以上含まれる → 「外国語/海外(中国語/簡体字)」
  H 非日本語 : ミャンマー/クメール/ラオス/タイ/キリル/アラビア/デーヴァナーガリー
                → 「外国語/海外(非日本語文字種)」
  I 反復ASCII: 同じ英字が 8 文字以上連続 → 「ハッシュタグNG(同一英字連続)」

入力は呼び出し側で _cs_* 系の strip 済み値を渡す:
  uid_s, name_s, bio_s, tags
"""
from __future__ import annotations

import re

# `letters_only` を作るときに使う。uid_clean は既に小文字なので a-z 以外を除去。
_LETTERS_ONLY = re.compile(r"[^a-z]")
# y を除外した連続子音 3 文字以上。日本語ローマ字には現れない並び。
_LONG_CONSONANT_RUN = re.compile(r"[bcdfghjklmnpqrstvwxz]{3,}")

_EXPLICIT_NG_WORDS: list[str] = [
    "絡み募", "絡み募集", "地雷",
    "xuhuong", "gaixinh", "xinhdep", "cewek", "wanita", "cantik", "mencari",
    "daun muda", "vaycongchua", "phongcachphap", "bachnguyetquang",
    "stylenangtho", "outfitlangman",
    "cortis", "onephony", "田島櫻子",
    "slipknot", "metal",
    "affiliate", "affiliatemarketing",
    "no bio yet", "No bio yet",
    "女装", "女装男子", "男の娘", "偽娘", "ニューハーフ",
]

_UNDERAGE_WORDS: list[str] = [
    "未成年", "中学生", "高校生",
    "jc", "jc1", "jc2", "jc3",
    "jk1", "jk2", "jk3", "fjk", "sjk", "ljk",
    "15さい", "15歳", "15才", "１５さい", "１５歳", "１５才",
    "14さい", "14歳", "14才", "１４さい", "１４歳", "１４才",
    "13さい", "13歳", "13才", "１３さい", "１３歳", "１３才",
    "16さい", "16歳", "16才", "１６さい", "１６歳", "１６才",
    "17さい", "17歳", "17才", "１７さい", "１７歳", "１７才",
]

_EXTERNAL_LINKS: list[str] = [
    "facebook.com", "mibextid",
    "onlyfans", "ofans", "fansly",
    "beacons.ai", "linktr.ee",
    # 個人ランディングページ系(他プラットフォーム誘導の温床)。
    # 海外個人クリエイターが Instagram/OnlyFans 等への動線として常用する。
    "carrd.co",
    "bento.me",
    "bio.link",
    "linkin.bio",
]

_CN_PHRASES: list[str] = [
    "今天", "也是", "电影", "治愈", "的一天",
    "关注", "私信", "主页", "置顶", "找我",
    "美女", "漂亮", "可爱", "点赞", "评论", "转发", "视频",
    "大家好", "我是", "喜欢",
]

# よく出る簡体字。2 文字以上一致で中国語と判定する。
_SIMPLIFIED_CHARS = "这们为热电说话买卖体会觉让从给发欢乐国学广东网写气应旧后边过还进长门"

_FULLWIDTH_TO_HALFWIDTH = str.maketrans("０１２３４５６７８９", "0123456789")
_JP_HANZI_KANA = re.compile(r"[ぁ-んァ-ヶ一-龥]")
_KANA_ONLY = re.compile(r"[ぁ-んァ-ヶ]")
_ASCII_LETTER = re.compile(r"[a-zA-Z]")
_TAG_TOKEN_SPLIT = re.compile(r"[#＃\s,，、/／｜|・.．。:_\-－ー]+")
_AGE_TEXT_PATTERN = re.compile(r"(?<![0-9])(?:1[0-7]|[0-9])\s*(?:歳|才|さい|サイ|ｻｲ)(?![0-9])")
_UID_NON_ALNUM = re.compile(r"[^a-zA-Z0-9]")
_UID_LETTER = re.compile(r"[a-z]")
_UID_DIGIT = re.compile(r"[0-9]")
_CN_BIO_HANZI = re.compile(r"[一-鿿]")
# ミャンマー / クメール / ラオス / タイ / キリル / アラビア / デーヴァナーガリー
_NON_JP_SCRIPTS = re.compile(
    r"[က-႟ក-៿຀-໿฀-๿Ѐ-ӿ؀-ۿऀ-ॿ]"
)
_REPEATED_LETTER_TAG = re.compile(r"(?i)(?<![a-z])([a-z])\1{7,}(?![a-z])")


def check(uid_s: str, name_s: str, bio_s: str, tags: str) -> str | None:
    full = " ".join([uid_s, name_s, tags, bio_s])
    low = full.lower()
    tags_low = tags.lower()

    has_japanese = _JP_HANZI_KANA.search(full) is not None
    has_kana = _KANA_ONLY.search(full) is not None
    has_ascii_tags = _ASCII_LETTER.search(tags) is not None
    has_ascii_bio = _ASCII_LETTER.search(bio_s) is not None

    # A. 明示NG
    for w in _EXPLICIT_NG_WORDS:
        ws = str(w or "").strip()
        if ws and ws.lower() in low:
            return f"類似除外({ws})"

    # B. 未成年(タグトークン 08/09 → ワードリスト → 年齢正規)
    tags_digits = tags.translate(_FULLWIDTH_TO_HALFWIDTH)
    tag_tokens = [t for t in _TAG_TOKEN_SPLIT.split(tags_digits) if t]
    if "08" in tag_tokens:
        return "ハッシュタグNG(08/未成年系)"
    if "09" in tag_tokens:
        return "ハッシュタグNG(09/未成年系)"

    for uw in _UNDERAGE_WORDS:
        uws = str(uw or "").strip()
        if uws and uws.lower() in low:
            return f"未成年系NG({uws})"

    age_text = full.translate(_FULLWIDTH_TO_HALFWIDTH)
    if _AGE_TEXT_PATTERN.search(age_text):
        return "未成年系NG(年齢表記)"

    # C. 外部リンク(litlink / lit.link は除外しない)
    has_litlink = ("lit.link" in low) or ("litlink" in low)
    for link in _EXTERNAL_LINKS:
        if link in low and not has_litlink:
            return f"外部リンクNG({link})"

    # D. ランダムID + 日本語要素が薄い/海外っぽい
    uid_clean = _UID_NON_ALNUM.sub("", uid_s).lower()
    uid_has_letter = _UID_LETTER.search(uid_clean) is not None
    uid_has_digit = _UID_DIGIT.search(uid_clean) is not None
    uid_has_sep = ("_" in uid_s) or ("." in uid_s) or ("-" in uid_s)
    if len(uid_clean) >= 7 and uid_has_letter and uid_has_digit and not uid_has_sep:
        if not has_kana or bio_s == "" or has_ascii_tags:
            # 英字部分(数字除く)に y を除いた連続子音が 3 文字以上ある場合は
            # 日本人ローマ字名(amane / haruka / yui 等)ではあり得ない並びなので
            # 「完全英字 = 海外確定」と判定して AI override の対象外にする。
            # amanecco721 のような日本人風サフィックス命名は連続子音が 2 以下
            # で済むので従来通り「ランダムID/海外・量産寄り」→ AI 救出経路。
            letters_only = _LETTERS_ONLY.sub("", uid_clean)
            if _LONG_CONSONANT_RUN.search(letters_only):
                return "ランダムID/完全英字(海外)"
            return "ランダムID/海外・量産寄り"

    # E. 英字タグ中心 + 日本語なし/短文bio
    if has_ascii_tags and not has_japanese:
        if bio_s == "" or len(bio_s) <= 30:
            return "外国語/海外(英字タグ中心+日本語なし)"

    # F. fyp + 日本語要素薄い
    if "fyp" in tags_low and not has_kana:
        if bio_s == "" or has_ascii_bio or _CN_BIO_HANZI.search(bio_s):
            return "外国語/海外(fyp+日本語要素薄い)"

    # G. 中国語
    for cn in _CN_PHRASES:
        if cn in full:
            return f"外国語/海外(中国語:{cn})"
    if sum(1 for ch in _SIMPLIFIED_CHARS if ch in full) >= 2:
        return "外国語/海外(中国語/簡体字)"

    # H. 非日本語文字種
    if _NON_JP_SCRIPTS.search(full):
        return "外国語/海外(非日本語文字種)"

    # I. 同一英字連続タグ
    if _REPEATED_LETTER_TAG.search(tags):
        return "ハッシュタグNG(同一英字連続)"

    return None
