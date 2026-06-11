#!/bin/bash
# 検証ループを起動。
# 引数でスワイプ回数指定可:  ./2_run_probe.command 100

set -e
cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
  echo "venv がありません。先に 0_setup_mac.command を実行してください。"
  exit 1
fi

source .venv/bin/activate

N="${1:-60}"
echo "=== probe 起動 (スワイプ ${N} 回) ==="
python3 probe.py "$N"
