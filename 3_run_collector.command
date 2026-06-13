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

# === 記入者名(collector_name)の確定 ===
# 解決順: 環境変数 TIKTOK_COLLECTOR_NAME > .collector_name ファイル > 対話入力
# Sheets の B列にこの名前が入る。複数 PC で運用するときは PC ごとに別名にする。
# .collector_name が既にあっても起動時に毎回確認プロンプトを出して、変更したいときは
# その場で書き換えられる(.max_followers と同じパターン)。
if [ -z "$TIKTOK_COLLECTOR_NAME" ] && [ -f ".collector_name" ]; then
  TIKTOK_COLLECTOR_NAME="$(head -n 1 .collector_name | tr -d '\r\n' | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
fi

echo ""
if [ -n "$TIKTOK_COLLECTOR_NAME" ]; then
  echo "現在の記入者名: $TIKTOK_COLLECTOR_NAME"
  printf "変更する場合は新しい値を入力(そのままなら Enter)> "
  read -r NEW_NAME
  NEW_NAME="$(echo "$NEW_NAME" | tr -d '\r\n' | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
  if [ -n "$NEW_NAME" ]; then
    TIKTOK_COLLECTOR_NAME="$NEW_NAME"
    printf "%s\n" "$NEW_NAME" > .collector_name
    echo "→ .collector_name を更新しました"
  fi
else
  echo "記入者名(Sheets B列に入る名前)が未設定です。"
  echo "複数 PC で運用するときに区別できる名前を入力してください。"
  echo "例: 篠原-Mac1 / 篠原-Mac2 / 篠原-Studio"
  printf "記入者名> "
  read -r TIKTOK_COLLECTOR_NAME
  TIKTOK_COLLECTOR_NAME="$(echo "$TIKTOK_COLLECTOR_NAME" | tr -d '\r\n' | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
  if [ -z "$TIKTOK_COLLECTOR_NAME" ]; then
    echo "記入者名が空です。中断します。"
    exit 1
  fi
  printf "%s\n" "$TIKTOK_COLLECTOR_NAME" > .collector_name
  echo "→ .collector_name に保存しました(次回からは自動で読み込みます)"
fi

export TIKTOK_COLLECTOR_NAME

# === フォロワー数の下限(min_followers)・上限(max_followers)の確定 ===
# 解決順: 環境変数 > ファイル > 対話入力(現状値で Enter)
# 抽出条件は「下限 以上 ≦ follower < 上限」。下限を 0 にすると実質「上限 未満」だけになる(従来挙動)。
if [ -z "$TIKTOK_MIN_FOLLOWERS" ] && [ -f ".min_followers" ]; then
  TIKTOK_MIN_FOLLOWERS="$(head -n 1 .min_followers | tr -d '\r\n' | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
fi
if [ -z "$TIKTOK_MAX_FOLLOWERS" ] && [ -f ".max_followers" ]; then
  TIKTOK_MAX_FOLLOWERS="$(head -n 1 .max_followers | tr -d '\r\n' | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
fi

# 現状値(env or ファイル or config.yaml)を表示用に決める
CURRENT_MIN="$TIKTOK_MIN_FOLLOWERS"
if [ -z "$CURRENT_MIN" ]; then
  CURRENT_MIN="$(awk '/^rules:/{flag=1} flag && /^[[:space:]]+min_followers:/{print $2; exit}' config.yaml 2>/dev/null)"
fi
if [ -z "$CURRENT_MIN" ]; then
  CURRENT_MIN="0"
fi
CURRENT_MAX="$TIKTOK_MAX_FOLLOWERS"
if [ -z "$CURRENT_MAX" ]; then
  CURRENT_MAX="$(awk '/^rules:/{flag=1} flag && /^[[:space:]]+max_followers:/{print $2; exit}' config.yaml 2>/dev/null)"
fi
if [ -z "$CURRENT_MAX" ]; then
  CURRENT_MAX="2000"
fi

echo ""
echo "現在のフォロワー数しきい値: ${CURRENT_MIN} 以上 ${CURRENT_MAX} 未満を抽出対象"
printf "下限を変更する場合は新しい値を入力(そのままなら Enter)> "
read -r NEW_MIN
NEW_MIN="$(echo "$NEW_MIN" | tr -d '\r\n' | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
if [ -n "$NEW_MIN" ]; then
  case "$NEW_MIN" in
    ''|*[!0-9]*)
      echo "数値ではないため中断します: $NEW_MIN"
      exit 1
      ;;
  esac
  TIKTOK_MIN_FOLLOWERS="$NEW_MIN"
  printf "%s\n" "$NEW_MIN" > .min_followers
  echo "→ .min_followers に保存しました(次回からはこの値が初期値になります)"
else
  TIKTOK_MIN_FOLLOWERS="$CURRENT_MIN"
fi
export TIKTOK_MIN_FOLLOWERS

printf "上限を変更する場合は新しい値を入力(そのままなら Enter)> "
read -r NEW_MAX
NEW_MAX="$(echo "$NEW_MAX" | tr -d '\r\n' | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
if [ -n "$NEW_MAX" ]; then
  case "$NEW_MAX" in
    ''|*[!0-9]*)
      echo "数値ではないため中断します: $NEW_MAX"
      exit 1
      ;;
  esac
  TIKTOK_MAX_FOLLOWERS="$NEW_MAX"
  printf "%s\n" "$NEW_MAX" > .max_followers
  echo "→ .max_followers に保存しました(次回からはこの値が初期値になります)"
else
  TIKTOK_MAX_FOLLOWERS="$CURRENT_MAX"
fi
export TIKTOK_MAX_FOLLOWERS

if [ "$TIKTOK_MIN_FOLLOWERS" -ge "$TIKTOK_MAX_FOLLOWERS" ] 2>/dev/null; then
  echo "下限($TIKTOK_MIN_FOLLOWERS)が上限($TIKTOK_MAX_FOLLOWERS)以上になっています。中断します。"
  exit 1
fi

echo ""
echo "=== TikTokCollectorStealth 本体起動 ==="
echo "記入者名: $TIKTOK_COLLECTOR_NAME"
echo "抽出条件: フォロワー数 ${TIKTOK_MIN_FOLLOWERS} 以上 ${TIKTOK_MAX_FOLLOWERS} 未満"
echo ""
python3 main.py
