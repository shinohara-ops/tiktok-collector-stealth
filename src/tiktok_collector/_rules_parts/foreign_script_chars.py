from __future__ import annotations

import re

# 非日本語スクリプトを文字種ベースで判定する。
# キーワードリスト方式だと網羅できないので、Unicode 範囲で「一定数以上含まれていれば
# 外国語」と機械的に弾く。日本人が使う絵文字記号は範囲外なので誤発火しない。
#
# 既存の `foreign_account.py` 内の hangul 判定と同じ発想だが、これは
# `colored_leak_v2.check`(「ランダムID/海外・量産寄り」)より **前** に呼ばれる
# 順序で配線する。理由:`ランダムID` は AI override 対象なので、先にここで
# 弾いておかないと AI が画像で誤救出してしまう。

# キリル文字基本 + 補助。ロシア語/ウクライナ語/ブルガリア語/カザフ語など。
_CYRILLIC = re.compile(r"[Ѐ-ԯ]")
# アラビア文字基本 + 補助。
_ARABIC = re.compile(r"[؀-ۿݐ-ݿ]")
# タイ文字。
_THAI = re.compile(r"[฀-๿]")
# トルコ語固有の特殊文字。`ü ö ç` はドイツ語/フランス語/スペイン語と被るため除外し、
# トルコ語にしか出ない `ş ğ İ ı` だけを拾う。
_TURKISH = re.compile(r"[şŞğĞİı]")


def check(uid: str, name: str, bio: str, tags: str) -> str | None:
    text = " ".join([uid or "", name or "", bio or "", tags or ""])
    if len(_CYRILLIC.findall(text)) >= 3:
        return "外国語/海外(キリル文字)"
    if len(_ARABIC.findall(text)) >= 3:
        return "外国語/海外(アラビア文字)"
    if len(_THAI.findall(text)) >= 3:
        return "外国語/海外(タイ文字)"
    # トルコ語固有文字は使用頻度が低いので 2 文字以上で判定。
    if len(_TURKISH.findall(text)) >= 2:
        return "外国語/海外(トルコ語特殊文字)"
    return None
