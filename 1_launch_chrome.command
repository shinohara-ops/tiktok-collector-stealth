#!/bin/bash
# 専用Chromeを CDP ポート 9222 で起動する
# このChromeウィンドウは TikTokCollectorStealth 専用。普段のChromeとは別プロファイル。

set -e
cd "$(dirname "$0")"

PROFILE="$HOME/Library/Application Support/TikTokCollectorStealth"
mkdir -p "$PROFILE"

CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
if [ ! -x "$CHROME" ]; then
  echo "Google Chrome が /Applications にありません。"
  echo "Chromeをインストールしてから再実行してください。"
  exit 1
fi

# すでに 9222 で待ち受けてる Chrome があれば kill して再起動
if lsof -nP -iTCP:9222 -sTCP:LISTEN >/dev/null 2>&1; then
  echo "ポート9222で起動済みの Chrome を終了して再起動します..."
  pkill -f "remote-debugging-port=9222" || true
  sleep 2
fi

echo "=== TikTokCollectorStealth 専用Chromeを起動します ==="
echo "プロファイル: $PROFILE"
echo "CDPポート: 9222"
echo ""
echo "起動後にやること:"
echo "  1) TikTokに手動でログイン(初回のみ)"
echo "  2) おすすめフィードが見える状態にする"
echo "  3) ウィンドウは閉じずに、別Spaceに移動して放置"
echo "  4) 別ターミナルで 2_run_probe.command を起動"
echo ""

exec "$CHROME" \
  --remote-debugging-port=9222 \
  --user-data-dir="$PROFILE" \
  --no-first-run \
  --no-default-browser-check \
  --mute-audio \
  --window-size=1280,900 \
  https://www.tiktok.com/
