"""黄色行プロフィール分析スクリプト

おすすめタブの 8358 行目以降で黄色背景セルを持つ行のプロフィールデータを読み込み、
ハッシュタグ・Bio・表示名の頻出パターンを出力する。
rules.py のルール改善の材料として使う。

使い方:
    .venv/bin/python analyze_yellow_rows.py
"""
from __future__ import annotations

import sys
import re
from collections import Counter
from pathlib import Path

# パスを通す
sys.path.insert(0, str(Path(__file__).parent))

import yaml
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials as OAuthCredentials
from google.auth.transport.requests import Request

# ─── 設定 ───────────────────────────────────────────────────────────────────
CONFIG_PATH = "config.yaml"
TAB_NAME = "おすすめ"
START_ROW = 8589  # 8589行目以降の黄色行を解析
# col index (0-based): A=0 取得日時, B=1 収集者, C=2 ユーザーID, D=3 表示名,
#   E=4 フォロワー数, F=5 ハッシュタグ, G=6 プロフィール紹介文, H=7 可愛さ点数,
#   I=8 理由, J=9 使用モデル, K=10 プロフURL, L=11 投稿URL, M=12 スクショパス
COL_UID = 2
COL_DISPLAY = 3
COL_FOLLOWERS = 4
COL_HASHTAGS = 5
COL_BIO = 6
COL_SCORE = 7
COL_REASON = 8
# ─────────────────────────────────────────────────────────────────────────────

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


def _is_yellow_bg(bg: dict) -> bool:
    if not bg:
        return False
    r = float(bg.get("red", 0.0))
    g = float(bg.get("green", 0.0))
    b = float(bg.get("blue", 0.0))  # 省略=0 なので 0.0 がデフォルト
    return r >= 0.75 and g >= 0.70 and b <= 0.50


def load_sheets_service(cfg_raw: dict):
    oauth_json = cfg_raw.get("google_sheets", {}).get("oauth_client_json", "./credentials/oauth_client.json")
    token_json = cfg_raw.get("google_sheets", {}).get("oauth_token_json", "./credentials/token.json")
    token_path = Path(token_json)
    creds = None
    if token_path.exists():
        creds = OAuthCredentials.from_authorized_user_file(str(token_path), SCOPES)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    if not creds or not creds.valid:
        raise RuntimeError("認証が必要です。先に verify_ng_setup.py を実行してトークンを取得してください。")
    return build("sheets", "v4", credentials=creds)


def cell_val(values: list, col: int) -> str:
    if len(values) <= col:
        return ""
    return str(values[col].get("formattedValue", "")).strip()


def main():
    raw = yaml.safe_load(Path(CONFIG_PATH).read_text(encoding="utf-8")) or {}
    spreadsheet_id = raw.get("google_sheets", {}).get("spreadsheet_id", "")
    service = load_sheets_service(raw)

    print(f"シート読み込み中: {TAB_NAME}!A{START_ROW}:M ...", flush=True)

    response = service.spreadsheets().get(
        spreadsheetId=spreadsheet_id,
        ranges=[f"'{TAB_NAME}'!A{START_ROW}:M"],
        includeGridData=True,
    ).execute()

    rows_data = []
    for sheet in response.get("sheets", []):
        for data_range in sheet.get("data", []):
            for row_data in data_range.get("rowData", []):
                values = row_data.get("values", [])
                row_is_yellow = any(
                    _is_yellow_bg(
                        (c.get("userEnteredFormat") or {}).get("backgroundColor") or {}
                    )
                    for c in values
                )
                if not row_is_yellow:
                    continue
                rows_data.append(values)

    total = len(rows_data)
    print(f"黄色行: {total} 件\n")
    if total == 0:
        print("黄色行が見つかりませんでした。")
        print("ヒント: 別タブの場合は TAB_NAME を変更してください。")
        return

    # ─── プロフィール一覧 ────────────────────────────────────────────────────
    print("=" * 70)
    print("【プロフィール一覧】")
    print("=" * 70)
    for i, values in enumerate(rows_data, 1):
        uid = cell_val(values, COL_UID)
        display = cell_val(values, COL_DISPLAY)
        followers = cell_val(values, COL_FOLLOWERS)
        hashtags = cell_val(values, COL_HASHTAGS)
        bio = cell_val(values, COL_BIO)
        score = cell_val(values, COL_SCORE)
        reason = cell_val(values, COL_REASON)
        print(f"\n[{i}] @{uid} / {display} / フォロワー:{followers} / スコア:{score}")
        print(f"  Bio : {bio[:120]}")
        print(f"  Tags: {hashtags[:120]}")
        print(f"  採用理由: {reason[:80]}")

    # ─── ハッシュタグ頻度 ────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("【ハッシュタグ頻度 TOP30】")
    print("=" * 70)
    tag_counter: Counter = Counter()
    for values in rows_data:
        tags_raw = cell_val(values, COL_HASHTAGS)
        # "#タグ" または "タグ" 形式を正規化して集計
        for tag in re.findall(r"#?[\w぀-鿿！-｠]+", tags_raw):
            tag = tag.lstrip("#").lower()
            if tag:
                tag_counter[tag] += 1
    for tag, cnt in tag_counter.most_common(30):
        print(f"  {cnt:3d}  #{tag}")

    # ─── Bio 頻出フレーズ ─────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("【Bio 頻出フレーズ(3文字以上の単語、TOP30)】")
    print("=" * 70)
    bio_counter: Counter = Counter()
    for values in rows_data:
        bio = cell_val(values, COL_BIO)
        for word in re.findall(r"[\w぀-鿿！-｠]{3,}", bio):
            bio_counter[word.lower()] += 1
    for word, cnt in bio_counter.most_common(30):
        print(f"  {cnt:3d}  {word}")

    # ─── 表示名パターン ──────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("【表示名 一覧】")
    print("=" * 70)
    for values in rows_data:
        uid = cell_val(values, COL_UID)
        display = cell_val(values, COL_DISPLAY)
        print(f"  @{uid:<30} {display}")

    # ─── Bio 全文(短い場合) ───────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("【Bio 全文】")
    print("=" * 70)
    for values in rows_data:
        uid = cell_val(values, COL_UID)
        bio = cell_val(values, COL_BIO)
        if bio:
            print(f"  @{uid}: {bio}")


if __name__ == "__main__":
    main()
