#!/bin/bash
# 採用書き込み用の帯域別タブ(おすすめ0-1000 等)を Sheets に一括作成する。
# main.py を起動せず Sheets API だけを叩く。初回 + 帯域定義変更時に手動実行。

set -e
cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
  echo "venv がありません。先に 0_setup_mac.command を実行してください。"
  exit 1
fi
source .venv/bin/activate

python3 bootstrap_recommended_tabs.py
