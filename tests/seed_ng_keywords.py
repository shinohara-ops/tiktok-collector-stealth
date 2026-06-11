"""
現状 rules.py / config.yaml にハードコードされている代表的な NG ワードを
Sheets「NGワード」タブに転写する一発スクリプト。

転写するもの(計 77 行):
  1. config.yaml の rules.ng_keywords(25 個) → general / all / FALSE
  2. rules.py の _colored_leak_ng_words_v2(50 個)→ general / all / FALSE
  3. 「可愛」「可愛い」(ハッシュタグ単体NG)→ general / hashtag / TRUE

冪等性:
  既存 Sheets 行のワード列を読み、同じワードがあれば追加しない。
  なので何回実行しても重複しない。

副作用:
  既存ハードコードは残したままなので、Sheets に同じワードを入れても
  reason 文字列は同じ "NGワード(xxx)"。snapshot test は緑のまま。
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


CONFIG_PATH = PROJECT_ROOT / "config.yaml"


@dataclass
class _SheetsCfgLite:
    spreadsheet_id: str
    tabs: dict
    auth_mode: str = "oauth"
    oauth_client_json: str = "./credentials/oauth_client.json"
    oauth_token_json: str = "./credentials/token.json"
    service_account_json: str = "./credentials/service_account.json"
    ng_keywords_cache_ttl_sec: int = 600


# rules.py の _colored_leak_ng_words_v2 と完全一致
COLORED_LEAK_NG_WORDS_V2 = [
    'Doublefedora', 'mafioso', 'forsaken', 'ベトナムフェスティバル', 'ウエノデコリアンフェスタ',
    'コリアンフェスタ', 'カリブラテンアメリカストリート', 'ラテンアメリカ', '日比谷音楽祭',
    'アウトドアシネマ', 'スタンダップコメディ', 'standupcomedy', 'crowdwork', 'ほんまやでダンス',
    'newmusic', 'いいねください', 'fypツ', 'smail', 'facebook.com', 'mibextid',
    '可愛い女の子', '毎日 可愛い女の子', '宝鐘マリン', 'くださいませチャレンジ', '愛くださいませ',
    '成熟した女性', '成熟', 'cosplay', 'cosplayer', 'neongenesisevangelion', 'アスカ',
    'lingerie', 'gorgeous', 'MagneticBeauty', 'SelfLoveVibes', 'GlamAndGrow',
    'ConfidenceIsKey', 'PR エバーカラー', 'エバーカラー', 'カラコン', 'ROWfreelove',
    'rowlove', 'rowbuzz', 'charlesandsylvia', 'wolfieandsylvia', 'couplescomedy',
    'じゅんな', 'ゆうな',
]

HASHTAG_ONLY_BIO_EMPTY = ['可愛', '可愛い']


def _load_client() -> SheetsClient:
    raw = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
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
    return SheetsClient(cfg)


def _read_existing(client: SheetsClient) -> set[tuple[str, str]]:
    """既存行を (カテゴリ小文字, ワード小文字) のセットで返す。"""
    tab = client.tabs.get("ng_keywords")
    resp = client.service.spreadsheets().values().get(
        spreadsheetId=client.spreadsheet_id,
        range=f"{tab}!A3:B",  # 1行目=説明、2行目=ヘッダー、3行目以降=データ
    ).execute()
    existing = set()
    for row in resp.get("values", []) or []:
        if len(row) >= 2:
            cat = str(row[0] or "").strip().lower()
            word = str(row[1] or "").strip().lower()
            if cat and word:
                existing.add((cat, word))
    return existing


def main() -> int:
    print("=== NGワード タブ シード ===", flush=True)
    client = _load_client()

    # 既存行
    existing = _read_existing(client)
    print(f"既存ワード行数: {len(existing)}", flush=True)

    # config.yaml の ng_keywords
    raw = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
    yaml_ng_keywords = list((raw.get("rules", {}) or {}).get("ng_keywords", []) or [])

    rows_to_append: list[list] = []

    def _add(category: str, word: str, scope: str, bio_empty_required: bool, memo: str) -> None:
        key = (category.lower(), word.lower())
        if key in existing:
            return
        existing.add(key)
        rows_to_append.append([
            category,
            word,
            "TRUE",
            memo,
            scope,
            "TRUE" if bio_empty_required else "FALSE",
        ])

    for w in yaml_ng_keywords:
        _add("general", str(w), "all", False, "config.yaml の rules.ng_keywords から移植")
    for w in COLORED_LEAK_NG_WORDS_V2:
        _add("general", str(w), "all", False, "_colored_leak_ng_words_v2 から移植(色付き漏れ対策)")
    for w in HASHTAG_ONLY_BIO_EMPTY:
        _add("general", str(w), "hashtag", True, "ハッシュタグ単体NG(可愛)挙動 — Bio 空のときだけ NG")

    if not rows_to_append:
        print("追加なし(全て既存)", flush=True)
        return 0

    tab = client.tabs["ng_keywords"]
    client.service.spreadsheets().values().append(
        spreadsheetId=client.spreadsheet_id,
        range=f"{tab}!A:F",
        valueInputOption="RAW",
        insertDataOption="INSERT_ROWS",
        body={"values": rows_to_append},
    ).execute()
    print(f"追加: {len(rows_to_append)} 行", flush=True)
    for r in rows_to_append[:8]:
        print(f"  {r}")
    if len(rows_to_append) > 8:
        print(f"  ...(+ {len(rows_to_append) - 8} 行)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
