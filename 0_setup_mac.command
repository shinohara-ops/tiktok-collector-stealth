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

# Homebrew Python を優先(OpenSSL ビルド)。なければシステム python3 を使う。
PYTHON3=""
for candidate in \
  /opt/homebrew/bin/python3.12 \
  /opt/homebrew/bin/python3.11 \
  /opt/homebrew/bin/python3.10 \
  /usr/local/bin/python3.12 \
  /usr/local/bin/python3.11 \
  /usr/local/bin/python3.10 \
  python3
do
  if command -v "$candidate" >/dev/null 2>&1; then
    PYTHON3="$candidate"
    break
  fi
done

if [ -z "$PYTHON3" ]; then
  echo "❌ python3 が見つかりません。Python 3.10+ をインストールしてください。"
  echo "   https://www.python.org/downloads/macos/ からダウンロードできます。"
  read -p "Enter で閉じる..."
  exit 1
fi

# Python バージョンチェック (3.10 未満は LibreSSL 問題で SSL クラッシュするため拒否)
PY_VER=$("$PYTHON3" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PY_MAJOR=$(echo "$PY_VER" | cut -d. -f1)
PY_MINOR=$(echo "$PY_VER" | cut -d. -f2)
if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 10 ]; }; then
  echo "❌ Python $PY_VER は非対応です（3.10 以上が必要）。"
  echo ""
  echo "  Python 3.9 以下の macOS 標準 Python は LibreSSL でビルドされており、"
  echo "  SSL 通信が途中でクラッシュします。"
  echo ""
  echo "  ▶ 解決方法: Homebrew で Python 3.12 をインストールしてください。"
  echo "    1) Terminal で以下を実行:"
  echo "       /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\""
  echo "    2) brew install python@3.12"
  echo "    3) このセットアップを再実行"
  read -p "Enter で閉じる..."
  exit 1
fi

echo "Python $PY_VER ($PYTHON3) を使用します。"

if [ ! -d ".venv" ]; then
  echo "venv を作成中..."
  "$PYTHON3" -m venv .venv
fi

# pip がない場合は ensurepip でブートストラップ(macOS システム Python で起こりやすい)
if [ ! -f ".venv/bin/pip" ]; then
  echo "pip を初期化中..."
  "$PYTHON3" -m ensurepip --upgrade 2>/dev/null || true
fi

echo "pip を更新中..."
.venv/bin/python -m pip install --upgrade pip --quiet

echo "probe 用の依存をインストール中..."
.venv/bin/python -m pip install -r requirements.txt

echo "本体 collector 用の依存をインストール中(openai / google-api / pillow 等)..."
.venv/bin/python -m pip install -r requirements_collector.txt

# update.command の最後で snapshot test を走らせるため pytest も入れる。
# 入れていないと初回 update.command で "No module named pytest" になり社員さんを不安にさせる。
if [ -f requirements_dev.txt ]; then
  echo "dev 用依存(pytest 等)をインストール中..."
  .venv/bin/python -m pip install -r requirements_dev.txt
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
