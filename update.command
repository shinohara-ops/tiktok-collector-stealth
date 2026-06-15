#!/bin/bash
# TikTokCollectorStealth アップデート用ワンクリック。
# ダブルクリック、または以下のコマンドをターミナルにベタ張りで実行可:
#   bash ~/Documents/coursol_work/tiktok-collector-stealth/update.command
#
# 動作:
#   1. ローカル未コミット変更は一旦退避 (git stash)
#   2. github から最新コードを取得 (git pull --rebase)
#   3. 退避した変更を復元
#   4. requirements.txt に追加があれば pip install
#   5. ルール挙動の自動テストを軽く確認

set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$HERE/.." && pwd)"

echo "============================================="
echo " TikTokCollectorStealth アップデート"
echo "============================================="
echo ""

# 旧モノリポ構成(coursol_work/tiktok-collector-stealth)では .git が一段上、
# 新スタンドアロン構成(tiktok-collector-stealth 単体)では .git が同じディレクトリ。
# 両方で動かせるよう自動判定する。
if [ -d "$HERE/.git" ]; then
  REPO_ROOT="$HERE"
fi
cd "$REPO_ROOT"

if [ ! -d ".git" ]; then
  echo "❌ ここは git リポジトリではありません: $REPO_ROOT"
  echo "  最初に git clone してください。"
  read -p "Enter で閉じる..."
  exit 1
fi

# ─── 1. ローカル変更があったら退避 ─────────────────────────────
STASHED=0
if ! git diff --quiet || ! git diff --cached --quiet; then
  STASH_LABEL="update.command auto-stash @ $(date '+%Y-%m-%d %H:%M:%S')"
  echo "[1/4] ローカル変更を一時退避: $STASH_LABEL"
  git stash push -u -m "$STASH_LABEL"
  STASHED=1
else
  echo "[1/4] ローカル変更なし(退避スキップ)"
fi

# ─── 2. github から pull ─────────────────────────────────────
echo "[2/4] GitHub から最新コードを取得 (git pull --rebase origin main)"
if ! git pull --rebase origin main; then
  echo ""
  echo "❌ git pull に失敗しました。"
  if [ "$STASHED" = "1" ]; then
    echo "  退避したローカル変更は git stash list で確認できます。"
  fi
  read -p "Enter で閉じる..."
  exit 1
fi

# ─── 3. 退避した変更を復元 ─────────────────────────────────────
if [ "$STASHED" = "1" ]; then
  echo "[3/4] 退避したローカル変更を復元 (git stash pop)"
  if ! git stash pop; then
    echo ""
    echo "⚠ stash pop でコンフリクトが発生しました。"
    echo "  リモートと同じファイルをローカルでも編集していた可能性があります。"
    echo "  以下で手動解決してください:"
    echo "    cd $REPO_ROOT"
    echo "    git status                # 競合ファイル確認"
    echo "    # 競合解消後:"
    echo "    git add <ファイル>"
    echo "    git stash drop            # 退避を破棄"
    read -p "Enter で閉じる..."
    exit 1
  fi
else
  echo "[3/4] 復元する退避なし(スキップ)"
fi

# ─── 4. Python 依存を更新 ───────────────────────────────────
cd "$HERE"
if [ ! -d ".venv" ]; then
  echo ""
  echo "⚠ .venv がありません。初回セットアップが必要です:"
  echo "  bash $HERE/0_setup_mac.command"
  read -p "Enter で閉じる..."
  exit 1
fi

echo "[4/4] Python 依存を確認・更新"
.venv/bin/pip install -r requirements.txt --quiet --upgrade-strategy only-if-needed || true
if [ -f requirements_collector.txt ]; then
  .venv/bin/pip install -r requirements_collector.txt --quiet --upgrade-strategy only-if-needed || true
fi

# ─── 動作確認(任意・失敗してもループは止めない) ────────────────
if [ -d tests ] && [ -f tests/test_rules_snapshot.py ]; then
  echo ""
  echo "→ ルール挙動の自動テストを実行..."
  if .venv/bin/python -m pytest tests/test_rules_snapshot.py tests/test_rules_scoped_ng.py -q 2>&1 | tail -3; then
    :
  else
    echo "⚠ テストが落ちました(挙動が変わっている可能性。本体起動前に確認推奨)"
  fi
fi

echo ""
echo "============================================="
echo " ✅ アップデート完了"
echo "============================================="
echo ""
echo "次の起動から最新版で動きます。"
echo "  → 3_run_collector.command で本体起動"
echo ""
read -p "Enter で閉じる..."
