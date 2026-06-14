"""採用書き込み用の帯域別タブ(おすすめ0-1000 等)を Sheets に一括作成する。

config.yaml の google_sheets.recommended_tab_ranges を読んで、SheetsClient を
初期化するだけ。SheetsClient.__init__ → _ensure_tabs → _ensure_recommended_range_tabs
が走って、不足タブの作成 + ヘッダー設定 + 書式設定までやる。

main.py を起動せずにタブだけ揃えたい時に使う(初回 + 帯域定義変更時)。
2 回目以降は 3_run_collector.command / 4_overnight_run.command の起動時に
自動で同じことが走るので、手動実行は不要。
"""
from __future__ import annotations

import sys
import yaml
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from src.tiktok_collector.sheets import SheetsClient


@dataclass
class _SheetsCfg:
    spreadsheet_id: str
    tabs: dict
    recommended_tab_ranges: list = field(default_factory=list)
    auth_mode: str = "oauth"
    oauth_client_json: str = "./credentials/oauth_client.json"
    oauth_token_json: str = "./credentials/token.json"
    service_account_json: str = "./credentials/service_account.json"
    ng_keywords_cache_ttl_sec: int = 600


def main() -> int:
    cfg_path = Path("config.yaml")
    if not cfg_path.exists():
        print("config.yaml が見つかりません。")
        return 1
    raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    gs = raw.get("google_sheets", {}) or {}
    ranges = gs.get("recommended_tab_ranges", []) or []

    print("=== 帯域別タブ bootstrap ===")
    print(f"spreadsheet_id: {gs.get('spreadsheet_id')}")
    print(f"帯域定義: {len(ranges)} 件")
    for r in ranges:
        print(f"  {r.get('min')}〜{r.get('max')}: {r.get('name')}")
    if not ranges:
        print("recommended_tab_ranges が空です。config.yaml を確認してください。")
        return 1

    cfg = _SheetsCfg(
        spreadsheet_id=gs.get("spreadsheet_id", ""),
        tabs=gs.get("tabs", {}) or {},
        recommended_tab_ranges=ranges,
        auth_mode=gs.get("auth_mode", "oauth"),
        oauth_client_json=gs.get("oauth_client_json", "./credentials/oauth_client.json"),
        oauth_token_json=gs.get("oauth_token_json", "./credentials/token.json"),
        service_account_json=gs.get("service_account_json", "./credentials/service_account.json"),
        ng_keywords_cache_ttl_sec=int(gs.get("ng_keywords_cache_ttl_sec", 600) or 600),
    )

    print("SheetsClient を初期化します(不足タブ作成 + ヘッダー + 書式)...")
    SheetsClient(cfg)
    print("完了。Sheets で確認してください。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
