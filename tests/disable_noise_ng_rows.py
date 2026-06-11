"""
Sheets「NGワード」タブの中で、単独 NG にすべきでないノイズ系の行を
有効=無効 に切り替える。

無効化対象(rules.py 上の行番号で識別):
  - L 273 _anonymous_for_loop : 類似除外の hardcoded フレーズ
                                (テンプレお借りしました等。短文の文字列マッチで
                                 普通の動画も巻き込む可能性が高い)
  - L 341 _anonymous_for_loop : 量産系ノイズタグ(capcut / fyp / おすすめ / ダンス
                                等。単独 NG ではなく「これらが多数 + Bio 空」で
                                量産系判定の COUNT シグナル用)
  - L 1922 _anonymous_for_loop : extra NG batch 1 の小規模リスト群
  - L 1935 / 1938 / 1944 _anonymous_for_loop : 同上

rules.py 側の hardcoded ループは無効化しない(本来の COUNT 判定で使われている)。
ここでは Sheets の seed エントリだけ無効化することで、scoped 判定の単独 NG ヒット
を止める。
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from src.tiktok_collector.sheets import SheetsClient  # noqa: E402


DISABLE_KEYWORDS_IN_MEMO = [
    "L273 _anonymous_for_loop",   # 類似除外
    "L341 _anonymous_for_loop",   # 量産系ノイズタグ
    "L1922 _anonymous_for_loop",
    "L1935 _anonymous_for_loop",
    "L1938 _anonymous_for_loop",
    "L1944 _anonymous_for_loop",
]


@dataclass
class _SheetsCfgLite:
    spreadsheet_id: str
    tabs: dict
    auth_mode: str = "oauth"
    oauth_client_json: str = "./credentials/oauth_client.json"
    oauth_token_json: str = "./credentials/token.json"
    service_account_json: str = "./credentials/service_account.json"
    ng_keywords_cache_ttl_sec: int = 600


def main() -> int:
    raw = yaml.safe_load((PROJECT_ROOT / "config.yaml").read_text(encoding="utf-8")) or {}
    gs = raw["google_sheets"]
    cfg = _SheetsCfgLite(
        spreadsheet_id=gs["spreadsheet_id"],
        tabs=gs["tabs"],
        auth_mode=gs.get("auth_mode", "oauth"),
        oauth_client_json=gs.get("oauth_client_json", "./credentials/oauth_client.json"),
        oauth_token_json=gs.get("oauth_token_json", "./credentials/token.json"),
        service_account_json=gs.get("service_account_json", "./credentials/service_account.json"),
        ng_keywords_cache_ttl_sec=int(gs.get("ng_keywords_cache_ttl_sec", 600)),
    )
    client = SheetsClient(cfg)
    tab = client.tabs["ng_keywords"]

    # 列順: A=カテゴリ B=ワード C=適用範囲 D=Bio空必須 E=有効 F=メモ
    resp = client.service.spreadsheets().values().get(
        spreadsheetId=client.spreadsheet_id,
        range=f"{tab}!A2:F",
    ).execute()
    rows = resp.get("values", []) or []
    print(f"対象行数: {len(rows)}")

    # 無効化したい行を見つける
    updates: list[tuple[int, list[str]]] = []  # (row_number_1based, new_row)
    counted = 0
    for i, row in enumerate(rows):
        new_row = list(row) + [""] * max(0, 6 - len(row))
        memo = str(new_row[5] or "")
        if not any(k in memo for k in DISABLE_KEYWORDS_IN_MEMO):
            continue
        counted += 1
        # 既に「無効」になっているならスキップ
        if str(new_row[4] or "").strip() in {"無効", "FALSE", "false", "0", "off", "OFF", "no", "NO"}:
            continue
        new_row[4] = "無効"
        sheet_row_no = i + 2  # ヘッダー(行1)分のオフセット
        updates.append((sheet_row_no, new_row))

    print(f"該当行(無効化候補): {counted}")
    print(f"今回 無効化する行: {len(updates)}")

    if updates:
        # 連続行は batchUpdate でまとめて、それ以外は個別
        data_payload = []
        for row_no, new_row in updates:
            data_payload.append({
                "range": f"{tab}!A{row_no}:F{row_no}",
                "values": [new_row],
            })

        # batchUpdate values で一気に
        client.service.spreadsheets().values().batchUpdate(
            spreadsheetId=client.spreadsheet_id,
            body={
                "valueInputOption": "RAW",
                "data": data_payload,
            },
        ).execute()
        print(f"完了: {len(updates)} 行を「無効」に")

    # 念のため結果確認
    resp = client.service.spreadsheets().values().get(
        spreadsheetId=client.spreadsheet_id,
        range=f"{tab}!E2:F",
    ).execute()
    rows = resp.get("values", []) or []
    enabled = sum(1 for r in rows if (len(r) > 0 and str(r[0] or "").strip() not in {"無効", "FALSE", "false", "0", "off", "OFF", "no", "NO"}))
    disabled = len(rows) - enabled
    print(f"\n最終状態: 有効 {enabled} / 無効 {disabled}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
