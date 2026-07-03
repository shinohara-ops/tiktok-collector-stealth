from __future__ import annotations

import asyncio
import sys
import traceback
from pathlib import Path
from src.tiktok_collector.config import load_config
from src.tiktok_collector.db import CollectorDB
from src.tiktok_collector.sheets import SheetsClient
from src.tiktok_collector.notifier import Notifier
from src.tiktok_collector.ai_judge import OpenAIJudge
from src.tiktok_collector.runner import TikTokRunner
from src.tiktok_collector import rules as rules_module


# data/RESTART_CHROME が touch されていたら exit code 77 を返す。
# 4_overnight_run.command がこの code を見て Chrome 全再起動 + main.py 再開する。
_EXIT_RESTART_CHROME = 77


async def main() -> int:
    print("=== TikTok Collector 起動準備 ===", flush=True)
    try:
        print("1/6 config.yaml 読み込み中...", flush=True)
        cfg = load_config("config.yaml")

        print("2/6 SQLiteログ準備中...", flush=True)
        db = CollectorDB(cfg.logging.sqlite_path)

        print("3/6 Google Sheets 接続確認中...", flush=True)
        print("ここで止まる場合は、Sheets API未有効・スプレッドシートID間違い・Google権限不足の可能性が高いです。", flush=True)
        sheets = SheetsClient(cfg.google_sheets)
        print("Google Sheets 接続OK", flush=True)

        # Sheets「NGワード」タブをカテゴリ別 NG ソースとして rules.py に登録。
        # 現時点ではタブは空の想定。シートに行を足すだけで判定に反映される(TTL内)。
        def _ng_provider(category: str) -> list[str]:
            try:
                return sheets.get_ng_keywords().get(category, [])
            except Exception:
                return []
        rules_module.set_ng_keyword_provider(_ng_provider)

        # メタ付き(scope=hashtag/bio/all、Bio空必須)のプロバイダ。
        # シートの E/F 列が空欄の行は scope=all / bio_empty_required=False のデフォルトになり、
        # 既存 _ng_provider と等価な挙動を示す(scoped 判定は付加情報)。
        def _ng_meta_provider(category: str) -> list[dict]:
            try:
                return sheets.get_ng_keywords_with_meta().get(category, [])
            except Exception:
                return []
        rules_module.set_ng_keyword_meta_provider(_ng_meta_provider)

        # 黄色セル除外: config.yellow_excluded_tab の指定行以降で黄色背景を持つ行のUID を除外。
        # 海外アカウント・なりすましアカウントをシートで黄色マークするだけで自動除外される。
        def _yellow_provider() -> frozenset:
            try:
                return sheets.get_yellow_excluded_uids()
            except Exception:
                return frozenset()
        rules_module.set_yellow_excluded_provider(_yellow_provider)

        print("4/6 Slack通知準備中...", flush=True)
        notifier = Notifier(cfg.slack)

        print("5/6 OpenAI準備中...", flush=True)
        ai = OpenAIJudge(cfg.openai)

        print("6/6 Playwright専用Chromeを起動します...", flush=True)
        runner = TikTokRunner(cfg, db, sheets, notifier, ai)
        await runner.run()
    except Exception as e:
        print("\n=== エラーで停止しました ===", flush=True)
        print(str(e), flush=True)
        print("\n--- 詳細 ---", flush=True)
        traceback.print_exc()
        print("\n上のエラー文をスクショで送ってください。", flush=True)
        return 1

    restart_flag = Path("data/RESTART_CHROME")
    if restart_flag.exists():
        try:
            restart_flag.unlink()
        except FileNotFoundError:
            pass
        return _EXIT_RESTART_CHROME
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
