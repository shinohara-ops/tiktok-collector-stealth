#!/bin/bash
# 初回セットアップ。venv作成 + Playwright導入。
# CDP接続するだけなので chromium バイナリ自体はDLしなくてもOKだが、
# 念のため入れておく(失敗しても無視)。
#
# ★ 初回のみ: このファイルを右クリック→「開く」で起動してください。
#   以降の .command ファイルは普通にダブルクリックで開けるようになります。

set -e
cd "$(dirname "$0")"

# --- Gatekeeper 隔離フラグを除去 ---
# zip で渡した場合に付く com.apple.quarantine を剥がす。
# これをしないと他の .command が「開発元を確認できない」で弾かれる。
xattr -dr com.apple.quarantine . 2>/dev/null || true
chmod +x ./*.command 2>/dev/null || true

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

echo "probe 用の依存をインストール中..."
pip install -r requirements.txt

echo "本体 collector 用の依存をインストール中(openai / google-api / pillow 等)..."
pip install -r requirements_collector.txt

# update.command の最後で snapshot test を走らせるため pytest も入れる。
# 入れていないと初回 update.command で "No module named pytest" になり社員さんを不安にさせる。
if [ -f requirements_dev.txt ]; then
  echo "dev 用依存(pytest 等)をインストール中..."
  pip install -r requirements_dev.txt
fi

# CDP接続方式なのでPlaywright純正Chromiumは不要(170MB DLを省略)。
# 実Chrome (/Applications/Google Chrome.app) を 1_launch_chrome.command で起動する。

# .env テンプレ作成。OPENAI_API_KEY を埋めないと 3_run_collector.command が失敗する。
if [ ! -f ".env" ]; then
  cat > .env <<'EOF'
# OpenAI API キーを設定してください(本体 collector の AI 判定に必須)。
# 例: OPENAI_API_KEY=sk-proj-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
OPENAI_API_KEY=
EOF
  echo ""
  echo "→ .env を作成しました。OPENAI_API_KEY を編集してください。"
  echo "   既存の TikTokCollector_FOR_MAC の .env からコピーすると早い。"
fi

echo ""
echo "=== セットアップ完了 ==="
echo "次の手順:"
echo "  1) .env を編集して OPENAI_API_KEY を入れる(本体起動に必須)"
echo "  2) 1_launch_chrome.command をダブルクリック → Chromeが起動"
echo "  3) TikTokにログインし、おすすめフィードが見える状態にする"
echo "  4) Chromeウィンドウを別Space(ミッションコントロールで作成)に移動"
echo "  5) 2_run_probe.command で検知耐性のヘルスチェック(任意)"
echo "  6) 3_run_collector.command で本体起動(AI判定 + Sheets書込み)"
echo ""
read -p "Enterで閉じる..."
