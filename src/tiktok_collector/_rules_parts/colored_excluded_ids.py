"""色付き除外 ID 群 — スプレッドシート上で色付けされた手動マーク uid をハードコード。

3 つの「色付き行スナップショット」を保持する。各リストは特定時期に共有シートで
特定の uid 群が「採用しない/類似が多い」として色付けマークされた集合を、
コードに転記したもの(履歴的に L2764 / L1650 / L1539 の3バッチで取り込まれた)。

判定はどれも同じ — unique_id が該当セットに含まれていれば
"色付き除外ID({uid})" を返す。

このモジュールは uid セットの所有とマッチング関数の提供だけを担当する。
呼び出し側は判定順を保つために 3 箇所で別々に呼ぶ:
  - L380 周辺: check_2764(uid)
  - L599 周辺: check_1650(uid)
  - L1415 周辺: check_1539(uid)
"""
from __future__ import annotations

_IDS_2764: frozenset[str] = frozenset({
    "na_.xl72", "m3i.64", "o8_kko7", "qxlyg",
    "antowanett_88", "naru13595", "14376_", "_________0.00",
    "q_r__zx", "parurun_chan1", "sfffed55", "o____12m",
    "kuu_86369",
})

_IDS_1650: frozenset[str] = frozenset({
    "ngminhchi335", "muxi6699", "osakana1225", "_ll.s10",
    "hozonyoudesu0", "neko22momo", "_n0zk", "maya181526",
    "xrbdwqgoceh", "umebosi_05", "mio0403018", "uu1313.t",
    "26zixy", "minpuri330",
})

_IDS_1539: frozenset[str] = frozenset({
    "erishinn", "layna0930", "olehistrinya43",
    "kata_kata_hati_yo", "nasyacuw3k",
    "una____1116", "uutkyds2189166932",
    "5dfgegd", "zella_matcha",
})


def _check(uid: str, ids: frozenset[str]) -> str | None:
    u = str(uid or "").strip().replace("@", "")
    if u and u in ids:
        return f"色付き除外ID({u})"
    return None


def check_2764(uid: str) -> str | None:
    return _check(uid, _IDS_2764)


def check_1650(uid: str) -> str | None:
    return _check(uid, _IDS_1650)


def check_1539(uid: str) -> str | None:
    return _check(uid, _IDS_1539)
