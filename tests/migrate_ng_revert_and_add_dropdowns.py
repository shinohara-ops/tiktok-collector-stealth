"""
NGワード タブを元のレイアウトに戻して、A/C/E/F 列にプルダウンを付ける。

戻すレイアウト:
  1 行目 = ヘッダー
  2 行目以降 = データ

操作:
  - 1 行目 (説明) を削除 → 自動で 2 行目(ヘッダー)が 1 行目に上がる
  - SheetsClient 初期化で _ensure_ng_dropdowns が走り、プルダウンが付く
    (再起動時にも自動で付き直す idempotent な実装)
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


def _load_client() -> SheetsClient:
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
    return SheetsClient(cfg)  # __init__ で _ensure_header → _ensure_ng_dropdowns が走る


def main() -> int:
    print("=== NGワード タブ: 説明行を削除 + プルダウン設定 ===", flush=True)
    client = _load_client()
    tab = client.tabs["ng_keywords"]
    sheet_id = client._sheet_id_by_title().get(tab)
    if sheet_id is None:
        print("FAIL: NGワードタブが見つからない")
        return 1

    # 1 行目の中身を確認
    resp = client.service.spreadsheets().values().get(
        spreadsheetId=client.spreadsheet_id,
        range=f"{tab}!A1:F2",
    ).execute()
    rows = resp.get("values", []) or []
    row1 = rows[0] if len(rows) >= 1 else []
    row2 = rows[1] if len(rows) >= 2 else []

    row1_first = str(row1[0]) if row1 else ""
    if "使い方" in row1_first or "NGワード設定" in row1_first:
        print(f"説明行を削除: A1='{row1_first[:60]}...'")
        client.service.spreadsheets().batchUpdate(
            spreadsheetId=client.spreadsheet_id,
            body={"requests": [{
                "deleteDimension": {
                    "range": {
                        "sheetId": sheet_id,
                        "dimension": "ROWS",
                        "startIndex": 0,
                        "endIndex": 1,
                    },
                },
            }]},
        ).execute()
        # 1 行目に書いた書式(背景色など)が残るので、新しい 1 行目をリセット
        client.service.spreadsheets().batchUpdate(
            spreadsheetId=client.spreadsheet_id,
            body={"requests": [{
                "repeatCell": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": 0,
                        "endRowIndex": 1,
                        "startColumnIndex": 0,
                        "endColumnIndex": 6,
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "textFormat": {"bold": True},
                            "wrapStrategy": "OVERFLOW_CELL",
                            "backgroundColor": {"red": 1.0, "green": 1.0, "blue": 1.0},
                        },
                    },
                    "fields": "userEnteredFormat(textFormat,wrapStrategy,backgroundColor)",
                },
            }]},
        ).execute()
        print("削除完了")
    elif "カテゴリ" in row1_first:
        print("既に元レイアウト(1 行目=ヘッダー)")
    else:
        print(f"想定外の状態: row1={row1!r}")

    # プルダウンは _ensure_ng_dropdowns が __init__ 時に既に張ったはずだが、
    # 念のため明示的にもう一度呼んでおく
    client._ensure_ng_dropdowns(tab)
    print("プルダウン設定完了(A列=カテゴリ、C列=有効、E列=適用範囲、F列=Bio空必須)")

    # 最終確認
    resp = client.service.spreadsheets().values().get(
        spreadsheetId=client.spreadsheet_id,
        range=f"{tab}!A1:F3",
    ).execute()
    rows = resp.get("values", []) or []
    print()
    print(f"行1 (ヘッダー): {rows[0] if rows else None}")
    print(f"行2 (データ先頭): {rows[1] if len(rows) >= 2 else None}")
    print(f"行3 (データ): {rows[2] if len(rows) >= 3 else None}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
