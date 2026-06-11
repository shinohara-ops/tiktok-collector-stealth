#!/bin/bash
# 初回セットアップ。venv作成 + Playwright導入。
# CDP接続するだけなので chromium バイナリ自体はDLしなくてもOKだが、
# 念のため入れておく(失敗しても無視)。

set -e
cd "$(dirname "$0")"

echo "=== TikTokCollectorStealth セットアップ ==="

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 が見つかりません。Python 3.11+ をインストールしてください。"
  exit 1
fi

if [ ! -d ".venv" ]; then
  echo "venv を作成中..."
  python3 -m venv .venv
fi

source .venv/bin/activate
echo "pip を更新中..."
pip install --upgrade pip --quiet

echo "依存パッケージをインストール中..."
pip install -r requirements.txt

# CDP接続方式なのでPlaywright純正Chromiumは不要(170MB DLを省略)。
# 実Chrome (/Applications/Google Chrome.app) を 1_launch_chrome.command で起動する。

echo ""
echo "=== セットアップ完了 ==="
echo "次の手順:"
echo "  1) 1_launch_chrome.command をダブルクリック → Chromeが起動"
echo "  2) TikTokにログインし、おすすめフィードが見える状態にする"
echo "  3) Chromeウィンドウを別Space(ミッションコントロールで作成)に移動"
echo "  4) 2_run_probe.command をダブルクリック → 検証ループ開始"
echo "  5) data/probe.jsonl で生存状況を確認"
echo ""
read -p "Enterで閉じる..."
