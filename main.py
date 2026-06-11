from __future__ import annotations

import asyncio
import traceback
from src.tiktok_collector.config import load_config
from src.tiktok_collector.db import CollectorDB
from src.tiktok_collector.sheets import SheetsClient
from src.tiktok_collector.notifier import Notifier
from src.tiktok_collector.ai_judge import OpenAIJudge
from src.tiktok_collector.runner import TikTokRunner
from src.tiktok_collector import rules as rules_module


async def main():
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


if __name__ == "__main__":
    asyncio.run(main())
