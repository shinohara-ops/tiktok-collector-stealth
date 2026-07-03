#!/bin/bash
cd "$(dirname "$0")"
HERE="$(pwd)"
PARENT="$(cd .. && pwd)"

echo "============================================="
echo " TikTokCollectorStealth Git 初期設定"
echo "============================================="
echo ""
echo "このPCで初めて update.command を使えるようにします。"
echo "GitHubのユーザー名とパスワード(またはトークン)の入力を求められる場合があります。"
echo ""

# Step 1: 個人設定をバックアップ
echo "[1/5] 個人設定をバックアップ..."
cp "$HERE/config.yaml" /tmp/_stealth_config_backup.yaml 2>/dev/null && echo "  config.yaml ✅" || echo "  config.yaml なし(スキップ)"
mkdir -p /tmp/_stealth_credentials_backup
cp -r "$HERE/credentials/." /tmp/_stealth_credentials_backup/ 2>/dev/null && echo "  credentials/ ✅" || echo "  credentials/ なし(スキップ)"

# Step 2: Downloads に git を初期化
echo ""
echo "[2/5] Git リポジトリを初期化..."
cd "$PARENT"
git init -q
git remote remove origin 2>/dev/null || true
git remote add origin https://github.com/shinohara-ops/coursol_work.git
echo "  リモート設定: https://github.com/shinohara-ops/coursol_work.git ✅"

# Step 3: tiktok-collector-stealth だけ取得
echo ""
echo "[3/5] GitHub から最新コードを取得中..."
echo "  (GitHubのログインを求められたら入力してください)"
if ! git fetch --depth=1 origin main 2>&1; then
    echo ""
    echo "❌ GitHub への接続に失敗しました。"
    echo "  ・インターネット接続を確認してください"
    echo "  ・GitHubのユーザー名・パスワードが正しいか確認してください"
    read -p "Enter で閉じる..."
    exit 1
fi
git checkout -B main --track origin/main -q 2>/dev/null || git checkout origin/main -- tiktok-collector-stealth/ 2>/dev/null
echo "  最新コード取得 ✅"

# Step 4: 個人設定を復元
echo ""
echo "[4/5] 個人設定を復元..."
if [ -f /tmp/_stealth_config_backup.yaml ]; then
    cp /tmp/_stealth_config_backup.yaml "$HERE/config.yaml"
    echo "  config.yaml ✅"
fi
if [ -d /tmp/_stealth_credentials_backup ] && [ "$(ls -A /tmp/_stealth_credentials_backup)" ]; then
    cp -r /tmp/_stealth_credentials_backup/. "$HERE/credentials/" 2>/dev/null
    echo "  credentials/ ✅"
fi

# Step 5: 確認
echo ""
echo "[5/5] 確認..."
cd "$PARENT"
if [ -d ".git" ]; then
    echo "  Git 設定 ✅"
    echo ""
    echo "============================================="
    echo " ✅ 初期設定完了！"
    echo "============================================="
    echo ""
    echo "今後のアップデートは update.command を"
    echo "ダブルクリックするだけでOKです。"
else
    echo ""
    echo "❌ 設定に失敗しました。管理者に連絡してください。"
fi

echo ""
read -p "Enter で閉じる..."
