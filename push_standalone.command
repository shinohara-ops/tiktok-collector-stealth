#!/bin/bash
# コミット済み変更を全リポジトリへ一括 push するスクリプト。
#   1. coursol_work モノリポ (origin/main) に git push
#   2. 配布用 standalone リポジトリ (tiktok-collector-stealth) に git subtree push
#
# 使い方: このファイルをダブルクリック、または
#   bash ~/Documents/coursol_work/tiktok-collector-stealth/push_standalone.command
#
# ※ 通常の git push の代わりにこれを使うと、全 PC に確実に届く。

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
echo " 全リポジトリへ push"
echo "============================================="
echo ""

# ─── 1. モノリポ (origin) へ push ───────────────────────────
echo "⏳ [1/2] coursol_work (origin) へ push 中..."
git push origin main
echo "   ✅ origin push 完了"
echo ""

# ─── 2. standalone リポジトリへ push ────────────────────────
echo "⏳ [2/2] standalone (tiktok-collector-stealth) へ subtree push 中..."
echo "         (初回は少し時間がかかります)"
SPLIT_SHA=$(git subtree split --prefix=tiktok-collector-stealth HEAD)
echo "   split SHA: $SPLIT_SHA"
git push standalone "${SPLIT_SHA}:refs/heads/main"
echo "   ✅ standalone push 完了"

echo ""
echo "============================================="
echo " ✅ 全リポジトリへの同期完了"
echo "============================================="
echo ""
echo "配布先の各台で update.command を実行すると最新版に更新されます。"
echo ""
read -p "Enter で閉じる..."
