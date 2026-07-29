from __future__ import annotations

import asyncio
import fcntl
import signal
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


_EXIT_RESTART_CHROME = 77
_lock_fd = None  # グローバルで保持しないと GC に回収されて lock が外れる


def _acquire_process_lock() -> bool:
    """同一 PC 上での複数インスタンス同時起動を防ぐ OS レベルのファイルロック。
    flock は プロセス終了(クラッシュ含む)で自動解放されるためスタックしない。
    ロック取得失敗 → False を返す。"""
    global _lock_fd
    lock_path = Path("data/.collector.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        _lock_fd = lock_path.open("w")
        fcntl.flock(_lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except IOError:
        return False


def _install_signal_handlers() -> None:
    """SIGTERM / SIGABRT / SIGTRAP 等を受け取ったら Chrome 再起動フラグをセットして exit 77。
    ハードウェア起因の SIGTRAP (BRK 命令) は Python では捕捉できないが、
    ソフトウェア由来のシグナルはここで受け取ってシェルのリスタートループに繋げる。"""
    def _handler(signum: int, frame) -> None:
        names = {5: "SIGTRAP", 6: "SIGABRT", 10: "SIGBUS", 15: "SIGTERM"}
        name = names.get(signum, f"SIG{signum}")
        print(f"[{name}] シグナル受信 → Chrome 再起動フラグをセットして終了", flush=True)
        try:
            Path("data/RESTART_CHROME").touch()
        except Exception:
            pass
        sys.exit(_EXIT_RESTART_CHROME)

    for sig in (signal.SIGTERM, signal.SIGABRT, signal.SIGTRAP):
        try:
            signal.signal(sig, _handler)
        except (OSError, ValueError):
            pass


async def main() -> int:
    _install_signal_handlers()
    print("=== TikTok Collector 起動準備 ===", flush=True)

    if not _acquire_process_lock():
        print(
            "⚠ 別の TikTokCollector インスタンスが同じ PC で実行中です。\n"
            "  重複書き込みを防ぐため、このプロセスを終了します。\n"
            "  実行中のプロセスを確認してください: pgrep -fl 'python.*main.py'",
            flush=True,
        )
        return 1

    # --- 設定フェーズ: 失敗は設定ミスなので exit 1 (再起動ループを止める) ---
    try:
        print("1/6 config.yaml 読み込み中...", flush=True)
        cfg = load_config("config.yaml")

        print("2/6 SQLiteログ準備中...", flush=True)
        db = CollectorDB(cfg.logging.sqlite_path)

        print("3/6 Google Sheets 接続確認中...", flush=True)
        print("ここで止まる場合は、Sheets API未有効・スプレッドシートID間違い・Google権限不足の可能性が高いです。", flush=True)
        sheets = SheetsClient(cfg.google_sheets)
        print("Google Sheets 接続OK", flush=True)

        def _ng_provider(category: str) -> list[str]:
            try:
                return sheets.get_ng_keywords().get(category, [])
            except Exception:
                return []
        rules_module.set_ng_keyword_provider(_ng_provider)

        def _ng_meta_provider(category: str) -> list[dict]:
            try:
                return sheets.get_ng_keywords_with_meta().get(category, [])
            except Exception:
                return []
        rules_module.set_ng_keyword_meta_provider(_ng_meta_provider)

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
    except Exception as e:
        print("\n=== 起動設定エラーで停止しました ===", flush=True)
        print(str(e), flush=True)
        print("\n--- 詳細 ---", flush=True)
        traceback.print_exc()
        print("\n設定ファイルまたはAPI接続を確認してください。", flush=True)
        return 1  # 設定エラーは再起動ループを止める

    # --- 実行フェーズ: 予期しない例外は exit 77 (Chrome 再起動→自動再開) ---
    try:
        await runner.run()
    except KeyboardInterrupt:
        print("\nCtrl+C を受け取りました。", flush=True)
        return 130
    except Exception as e:
        print(f"\n=== ランタイムエラー ===\n{str(e)[:400]}", flush=True)
        traceback.print_exc()
        print("\n自動再起動します...", flush=True)
        try:
            Path("data/RESTART_CHROME").touch()
        except Exception:
            pass
        return _EXIT_RESTART_CHROME

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
