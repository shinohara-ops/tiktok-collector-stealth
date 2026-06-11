"""
NGワード タブの D 列(メモ)を末尾に移動して、列順を
  カテゴリ / ワード / 有効 / 適用範囲 / Bio空必須 / メモ
に変更する一発スクリプト。

操作:
  - moveDimension で D 列(0-based index=3)を 6 番目に移動
  - 既存データ 1112 行もそのまま列の順序が入れ替わる(Sheets が自動)
  - _ensure_ng_dropdowns を再実行してプルダウンの列を新位置に張り直す
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
    sheet_id = client._sheet_id_by_title().get(tab)
    if sheet_id is None:
        print("FAIL: NGワード タブが見つからない")
        return 1

    # 移動前にヘッダー確認
    resp = client.service.spreadsheets().values().get(
        spreadsheetId=client.spreadsheet_id,
        range=f"{tab}!A1:F1",
    ).execute()
    header = (resp.get("values") or [[]])[0]
    print(f"移動前ヘッダー: {header}")

    if header == ["カテゴリ", "ワード", "有効", "適用範囲", "Bio空必須", "メモ"]:
        print("既に新しい列順 — 何もしない")
    else:
        # D 列(0-based 3)を末尾(0-based 6)に移動
        client.service.spreadsheets().batchUpdate(
            spreadsheetId=client.spreadsheet_id,
            body={"requests": [{
                "moveDimension": {
                    "source": {
                        "sheetId": sheet_id,
                        "dimension": "COLUMNS",
                        "startIndex": 3,
                        "endIndex": 4,
                    },
                    "destinationIndex": 6,
                },
            }]},
        ).execute()
        print("D列(メモ)を末尾に移動しました")

    # プルダウンを新しい列インデックスで張り直す
    client._ensure_ng_dropdowns(tab)
    print("プルダウン再適用完了(新列順 A=カテゴリ / C=有効 / D=適用範囲 / E=Bio空必須)")

    # 結果確認
    resp = client.service.spreadsheets().values().get(
        spreadsheetId=client.spreadsheet_id,
        range=f"{tab}!A1:F3",
    ).execute()
    rows = resp.get("values", []) or []
    print()
    for i, r in enumerate(rows, start=1):
        print(f"行{i}: {r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
