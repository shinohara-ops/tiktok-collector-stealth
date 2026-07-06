#!/bin/bash
# 配布用リポジトリ (tiktok-collector-stealth) へ同期するスクリプト。
# coursol_work モノリポの tiktok-collector-stealth サブディレクトリを
# git subtree push で standalone リモートに反映する。
#
# 使い方: このファイルをダブルクリック、または
#   bash ~/Documents/coursol_work/tiktok-collector-stealth/push_standalone.command

set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$HERE/.." && pwd)"

# スタンドアロン構成(tiktok-collector-stealth 単体で .git がある)では不要なので終了
if [ -d "$HERE/.git" ]; then
  echo "スタンドアロン構成ではこのスクリプトは不要です。"
  read -p "Enter で閉じる..."
  exit 0
fi

cd "$REPO_ROOT"

if [ ! -d ".git" ]; then
  echo "❌ ここは git リポジトリではありません: $REPO_ROOT"
  read -p "Enter で閉じる..."
  exit 1
fi

# standalone リモートが未設定なら追加
if ! git remote get-url standalone &>/dev/null; then
  echo "standalone リモートを追加します..."
  git remote add standalone https://github.com/shinohara-ops/tiktok-collector-stealth
fi

echo "============================================="
echo " 配布用リポジトリへ同期 (git subtree push)"
echo " → github.com/shinohara-ops/tiktok-collector-stealth"
echo "============================================="
echo ""
echo "⏳ subtree split 中... (初回は少し時間がかかります)"

SPLIT_SHA=$(git subtree split --prefix=tiktok-collector-stealth HEAD)
echo "   split SHA: $SPLIT_SHA"
echo ""
echo "⏳ push 中..."
git push standalone "${SPLIT_SHA}:refs/heads/main"

echo ""
echo "============================================="
echo " ✅ 同期完了"
echo "============================================="
echo ""
echo "配布先の各台で update.command を実行すると最新版に更新されます。"
echo ""
read -p "Enter で閉じる..."
