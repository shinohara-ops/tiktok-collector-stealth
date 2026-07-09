"""昨夜のSQLite recommended 記録がSheetsに入っているか確認するスクリプト。"""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src.tiktok_collector.config import load_config
from src.tiktok_collector.sheets import SheetsClient

cfg = load_config("config.yaml")
sheets = SheetsClient(cfg.google_sheets)

# SQLiteから昨夜以降のrecommended一覧を取得
con = sqlite3.connect(cfg.logging.sqlite_path)
rows = con.execute(
    "SELECT unique_id, created_at FROM processed "
    "WHERE status='recommended' "
    "ORDER BY created_at"
).fetchall()
con.close()

print(f"SQLite recommended件数 (全期間): {len(rows)}件")
print("Sheetsと照合中...\n")

# Sheetsの全UIDを取得
sheet_uids = sheets.get_unique_id_status_map()

missing = []
found = []
for uid, created_at in rows:
    if uid in sheet_uids:
        found.append((uid, created_at, sheet_uids[uid]))
    else:
        missing.append((uid, created_at))

print(f"Sheets記載あり: {len(found)}件")
print(f"Sheets未記載 (漏れ): {len(missing)}件")

if missing:
    print("\n--- 漏れているUID ---")
    for uid, ts in missing:
        print(f"  {ts}  {uid}")
