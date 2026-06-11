"""
NGワード Sheets 連動の検証スクリプト。

main.py を通さず、SheetsClient だけを直接起動して以下を確認する:
  1. config.yaml の google_sheets セクションを読み込めるか
  2. SheetsClient 初期化で「NGワード」タブが Sheets 上に自動作成されるか
  3. 「NGワード」タブのヘッダー行(カテゴリ/ワード/有効/メモ)が書かれるか
  4. get_ng_keywords() が dict を返すか(初回は空)
  5. rules.py の _load_extra_words が provider と接続できるか

OPENAI_API_KEY も Playwright も不要。Chrome を起動しない。
"""
from __future__ import annotations

import sys
import yaml
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from src.tiktok_collector.sheets import SheetsClient, NG_KEYWORDS_HEADERS, NG_KEYWORDS_TAB_KEY
from src.tiktok_collector import rules as rules_module


@dataclass
class _SheetsCfg:
    spreadsheet_id: str
    tabs: dict
    auth_mode: str = "oauth"
    oauth_client_json: str = "./credentials/oauth_client.json"
    oauth_token_json: str = "./credentials/token.json"
    service_account_json: str = "./credentials/service_account.json"
    ng_keywords_cache_ttl_sec: int = 600


def main() -> int:
    print("=== NGワード連動 検証 ===", flush=True)

    cfg_path = Path("config.yaml")
    if not cfg_path.exists():
        print("config.yaml が見つからない。")
        return 1
    raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    gs = raw.get("google_sheets", {})

    print(f"spreadsheet_id: {gs.get('spreadsheet_id')}")
    print(f"tabs: {gs.get('tabs')}")
    print(f"ng_keywords_cache_ttl_sec: {gs.get('ng_keywords_cache_ttl_sec')}")

    if NG_KEYWORDS_TAB_KEY not in gs.get("tabs", {}):
        print(f"FAIL: tabs に {NG_KEYWORDS_TAB_KEY} が無い。config.yaml を確認。")
        return 1

    cred_path = Path(gs.get("oauth_client_json", "./credentials/oauth_client.json"))
    if not cred_path.exists():
        print()
        print(f"NG: credentials が無い: {cred_path}")
        print(" → 元 TikTokCollector の credentials/oauth_client.json をここにコピーしてください。")
        return 2

    cfg = _SheetsCfg(
        spreadsheet_id=gs["spreadsheet_id"],
        tabs=gs["tabs"],
        auth_mode=gs.get("auth_mode", "oauth"),
        oauth_client_json=gs.get("oauth_client_json", "./credentials/oauth_client.json"),
        oauth_token_json=gs.get("oauth_token_json", "./credentials/token.json"),
        service_account_json=gs.get("service_account_json", "./credentials/service_account.json"),
        ng_keywords_cache_ttl_sec=int(gs.get("ng_keywords_cache_ttl_sec", 600)),
    )

    print()
    print("SheetsClient を初期化(_ensure_tabs が走り、NGワードタブが無ければ作られる)...")
    client = SheetsClient(cfg)
    print("初期化 OK")

    print()
    print("Sheets のタブ一覧を取得して NGワードタブが実在するか確認...")
    titles = client._get_sheet_titles()
    ng_tab_title = cfg.tabs[NG_KEYWORDS_TAB_KEY]
    if ng_tab_title in titles:
        print(f"OK: '{ng_tab_title}' タブが存在する")
    else:
        print(f"FAIL: '{ng_tab_title}' タブが見当たらない。実在タブ: {titles}")
        return 3

    print()
    print(f"'{ng_tab_title}' のヘッダー行を取得...")
    resp = client.service.spreadsheets().values().get(
        spreadsheetId=cfg.spreadsheet_id,
        range=f"{ng_tab_title}!A1:D1",
    ).execute()
    header_row = (resp.get("values") or [[]])[0]
    print(f"  実際: {header_row}")
    print(f"  期待: {NG_KEYWORDS_HEADERS}")
    if header_row != NG_KEYWORDS_HEADERS:
        print("FAIL: ヘッダー行が一致しない")
        return 4
    print("OK: ヘッダー一致")

    print()
    print("get_ng_keywords() を呼び出し(初回はキャッシュ無し → Sheets fetch)...")
    kws = client.get_ng_keywords()
    print(f"  結果: {kws}")
    print(f"  キャッシュタイムスタンプ: {client._ng_cache_ts}")
    if not isinstance(kws, dict):
        print("FAIL: dict が返ってこない")
        return 5
    print("OK: dict 返却")

    print()
    print("rules.set_ng_keyword_provider() で provider 登録 → _load_extra_words 経路チェック...")
    rules_module.set_ng_keyword_provider(lambda cat: client.get_ng_keywords().get(cat, []))

    class _FakeRules:
        ng_keywords = ["yaml由来テスト"]
    merged = rules_module._load_extra_words(_FakeRules(), "ng_keywords")
    print(f"  _load_extra_words(ng_keywords) → {merged}")
    if "yaml由来テスト" not in merged:
        print("FAIL: yaml 由来ワードがマージされていない")
        return 6
    print("OK: yaml 由来は維持されている(Sheet 側が空なので merged は yaml だけ)")

    print()
    print("=== すべての検証項目をクリア ===")
    print()
    print("次の動作確認:")
    print(f"  1. Sheets を開く: https://docs.google.com/spreadsheets/d/{cfg.spreadsheet_id}")
    print(f"  2. '{ng_tab_title}' タブで A列にカテゴリ(例: general)、B列にワード(例: テスト除外)を入れる")
    print(f"  3. C列を TRUE にする")
    print(f"  4. {cfg.ng_keywords_cache_ttl_sec}秒以内に本スクリプトを再実行すると、キャッシュ経由(同じ結果)")
    print(f"     超えてから再実行すると、新規ワードが取れる")
    return 0


if __name__ == "__main__":
    sys.exit(main())
