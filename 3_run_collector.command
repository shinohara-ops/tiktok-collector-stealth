#!/bin/bash
# 本体 collector を起動(stealth 化された runner.py 経由)。
# 事前に 1_launch_chrome.command を起動して、TikTokにログイン・おすすめフィード表示済みであること。

set -e
cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
  echo "venv がありません。先に 0_setup_mac.command を実行してください。"
  exit 1
fi

source .venv/bin/activate

if [ ! -f ".env" ]; then
  echo "警告: .env がありません。OPENAI_API_KEY が必要です。"
  echo "      .env に OPENAI_API_KEY=sk-... を書いてから再実行してください。"
fi

if ! lsof -nP -iTCP:9222 -sTCP:LISTEN >/dev/null 2>&1; then
  echo "ポート9222で Chrome が見えません。先に 1_launch_chrome.command を起動してください。"
  exit 1
fi

echo "=== TikTokCollectorStealth 本体起動 ==="
python3 main.py
