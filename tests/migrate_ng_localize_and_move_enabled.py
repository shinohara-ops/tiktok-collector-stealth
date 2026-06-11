"""
NGワード タブを最終レイアウトに移行する一発スクリプト。

操作:
  1. C列(有効)を E 位置(右から二つ目)に移動
     現状: A=カテゴリ B=ワード C=有効 D=適用範囲 E=Bio空必須 F=メモ
     目標: A=カテゴリ B=ワード C=適用範囲 D=Bio空必須 E=有効 F=メモ
  2. 既存データを日本語ラベルに置換:
     カテゴリ : general → 汎用 / ng → NG / ad → 広告 / official → 公式 / agency → 事務所
                / live → 配信 / music → 音楽 / game → ゲーム / pet → ペット / food → 食べ物
     適用範囲 : all → 全体 / hashtag → ハッシュタグ / bio → Bio
     Bio空必須: TRUE → 必須 / FALSE → 不要
     有効     : TRUE → 有効 / FALSE → 無効
  3. プルダウン再設定(新列インデックス + 日本語候補)

冪等性:
  既に新しい列順 + 日本語ラベルになっていれば、ステップ1/2はスキップしてプルダウンだけ
  張り直す。何回でも実行できる。
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


CAT_MAP = {
    "general": "汎用",
    "ng": "NG",
    "ad": "広告",
    "official": "公式",
    "agency": "事務所",
    "live": "配信",
    "music": "音楽",
    "game": "ゲーム",
    "pet": "ペット",
    "food": "食べ物",
}
SCOPE_MAP = {"all": "全体", "hashtag": "ハッシュタグ", "bio": "Bio"}
BIO_EMPTY_MAP = {"TRUE": "必須", "FALSE": "不要"}
ENABLED_MAP = {"TRUE": "有効", "FALSE": "無効"}


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

    resp = client.service.spreadsheets().values().get(
        spreadsheetId=client.spreadsheet_id,
        range=f"{tab}!A1:F1",
    ).execute()
    header = (resp.get("values") or [[]])[0]
    print(f"移動前ヘッダー: {header}")

    target_header = ["カテゴリ", "ワード", "適用範囲", "Bio空必須", "有効", "メモ"]
    if header == target_header:
        print("既に新列順 — 列移動はスキップ")
    elif header == ["カテゴリ", "ワード", "有効", "適用範囲", "Bio空必須", "メモ"]:
        # 「有効」(C列, index=2)を E位置(削除後 index=4)に移動
        print("ステップ1: C列(有効)を E 位置に移動...")
        client.service.spreadsheets().batchUpdate(
            spreadsheetId=client.spreadsheet_id,
            body={"requests": [{
                "moveDimension": {
                    "source": {
                        "sheetId": sheet_id,
                        "dimension": "COLUMNS",
                        "startIndex": 2,
                        "endIndex": 3,
                    },
                    "destinationIndex": 5,
                },
            }]},
        ).execute()
    else:
        print(f"想定外のヘッダー(中断): {header}")
        return 2

    print("ステップ2: 既存値を日本語化...")
    resp = client.service.spreadsheets().values().get(
        spreadsheetId=client.spreadsheet_id,
        range=f"{tab}!A2:F",
    ).execute()
    rows = resp.get("values", []) or []
    print(f"  対象行: {len(rows)}")

    updated_rows: list[list] = []
    changed_count = 0
    for row in rows:
        new_row = list(row) + [""] * max(0, 6 - len(row))
        before = list(new_row)
        # 列順: 0=カテゴリ 1=ワード 2=適用範囲 3=Bio空必須 4=有効 5=メモ
        cat_l = str(new_row[0]).strip().lower()
        new_row[0] = CAT_MAP.get(cat_l, new_row[0])

        scope_l = str(new_row[2]).strip().lower()
        new_row[2] = SCOPE_MAP.get(scope_l, new_row[2])

        bio_u = str(new_row[3]).strip().upper()
        new_row[3] = BIO_EMPTY_MAP.get(bio_u, new_row[3])

        en_u = str(new_row[4]).strip().upper()
        new_row[4] = ENABLED_MAP.get(en_u, new_row[4])

        if new_row != before:
            changed_count += 1
        updated_rows.append(new_row)

    print(f"  値が変わる行: {changed_count}")
    if changed_count > 0:
        CHUNK = 500
        for i in range(0, len(updated_rows), CHUNK):
            batch = updated_rows[i:i + CHUNK]
            start_row = i + 2
            end_row = start_row + len(batch) - 1
            client.service.spreadsheets().values().update(
                spreadsheetId=client.spreadsheet_id,
                range=f"{tab}!A{start_row}:F{end_row}",
                valueInputOption="RAW",
                body={"values": batch},
            ).execute()
            print(f"  ... updated rows {start_row}..{end_row}", flush=True)

    print("ステップ3: プルダウン再設定...")
    client._ensure_ng_dropdowns(tab)

    # 結果
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
