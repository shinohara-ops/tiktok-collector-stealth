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
# TIKTOK_NONINTERACTIVE=1 のときは対話入力をスキップして .collector_name /
# .min_followers / .max_followers をそのまま使う(4_overnight_run.command 用)。
if [ -z "$TIKTOK_COLLECTOR_NAME" ] && [ -f ".collector_name" ]; then
  TIKTOK_COLLECTOR_NAME="$(head -n 1 .collector_name | tr -d '\r\n' | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
fi

if [ "$TIKTOK_NONINTERACTIVE" = "1" ]; then
  if [ -z "$TIKTOK_COLLECTOR_NAME" ]; then
    echo "TIKTOK_NONINTERACTIVE=1 ですが記入者名が未設定です(.collector_name 無し)。"
    echo "先に対話モードで一度起動して .collector_name を作ってください。"
    exit 1
  fi
  if [ -z "$TIKTOK_MIN_FOLLOWERS" ] && [ -f ".min_followers" ]; then
    TIKTOK_MIN_FOLLOWERS="$(head -n 1 .min_followers | tr -d '\r\n' | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
  fi
  if [ -z "$TIKTOK_MIN_FOLLOWERS" ]; then TIKTOK_MIN_FOLLOWERS="0"; fi
  if [ -z "$TIKTOK_MAX_FOLLOWERS" ] && [ -f ".max_followers" ]; then
    TIKTOK_MAX_FOLLOWERS="$(head -n 1 .max_followers | tr -d '\r\n' | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
  fi
  if [ -z "$TIKTOK_MAX_FOLLOWERS" ]; then TIKTOK_MAX_FOLLOWERS="2000"; fi
  export TIKTOK_COLLECTOR_NAME TIKTOK_MIN_FOLLOWERS TIKTOK_MAX_FOLLOWERS
  echo ""
  echo "=== TikTokCollectorStealth 本体起動(非対話モード)==="
  echo "記入者名: $TIKTOK_COLLECTOR_NAME"
  echo "抽出条件: フォロワー数 ${TIKTOK_MIN_FOLLOWERS} 以上 ${TIKTOK_MAX_FOLLOWERS} 未満"
  echo ""
  python3 main.py
  exit $?
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
echo "変更する場合の入力例: 10以上2500未満 / 10-2500 / 10 2500 / 2500(上限のみ)"
printf "変更する場合は新しい値を入力(そのままなら Enter)> "
read -r NEW_RANGE
NEW_RANGE="$(echo "$NEW_RANGE" | tr -d '\r\n' | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"

TIKTOK_MIN_FOLLOWERS="$CURRENT_MIN"
TIKTOK_MAX_FOLLOWERS="$CURRENT_MAX"

if [ -n "$NEW_RANGE" ]; then
  # 入力文字列から数字を全部抽出する。`10以上2500未満` → "10" "2500"。
  NUMS=()
  for n in $(echo "$NEW_RANGE" | grep -oE '[0-9]+'); do
    NUMS+=("$n")
  done
  case "${#NUMS[@]}" in
    2)
      TIKTOK_MIN_FOLLOWERS="${NUMS[0]}"
      TIKTOK_MAX_FOLLOWERS="${NUMS[1]}"
      printf "%s\n" "$TIKTOK_MIN_FOLLOWERS" > .min_followers
      printf "%s\n" "$TIKTOK_MAX_FOLLOWERS" > .max_followers
      echo "→ .min_followers / .max_followers に保存しました"
      ;;
    1)
      # 数字が 1 個だけ:文脈なら上限とみなす(下限は現状値維持)。
      TIKTOK_MAX_FOLLOWERS="${NUMS[0]}"
      printf "%s\n" "$TIKTOK_MAX_FOLLOWERS" > .max_followers
      echo "→ .max_followers のみ更新しました(下限は ${TIKTOK_MIN_FOLLOWERS} のまま)"
      ;;
    *)
      echo "数値を 1〜2 個含めて入力してください。中断します: $NEW_RANGE"
      exit 1
      ;;
  esac
fi

export TIKTOK_MIN_FOLLOWERS
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

# シグナル終了(SIGTRAP/SIGABRT 等)を含む予期しない終了を自動でリカバリする。
# 4_overnight_run.command と同じロジックをここにも持たせる。
CONSEC_ERR1=0
MAX_CONSEC_ERR1=3

while true; do
  set +e
  python3 main.py
  PY_EXIT=$?
  set -e

  # 正常終了 / Ctrl+C
  if [ "$PY_EXIT" -eq 0 ] || [ "$PY_EXIT" -eq 130 ]; then
    exit "$PY_EXIT"
  fi

  # Chrome 全再起動要求(フィード詰まり)
  if [ "$PY_EXIT" -eq 77 ]; then
    CONSEC_ERR1=0
    echo ""
    echo "--- Chrome 再起動要求(フィード詰まり): $(date '+%F %T') ---"
    pkill -f "TikTokCollectorStealth" 2>/dev/null || true
    pkill -f "remote-debugging-port=9222" 2>/dev/null || true
    sleep 5
    "$(dirname "$0")/1_launch_chrome.command" &
    echo "Chrome を再起動中... (最大 30 秒)"
    for _i in $(seq 1 30); do
      sleep 1
      if lsof -nP -iTCP:9222 -sTCP:LISTEN >/dev/null 2>&1; then break; fi
    done
    sleep 5
    echo "=== 再起動: $(date '+%F %T') ==="
    continue
  fi

  # シグナル終了 128+N (SIGTRAP=133, SIGABRT=134, SIGSEGV=139 等)
  if [ "$PY_EXIT" -ge 128 ] && [ "$PY_EXIT" -le 159 ]; then
    CONSEC_ERR1=0
    SIG=$((PY_EXIT - 128))
    echo ""
    echo "⚠️  シグナル ${SIG} で終了(exit ${PY_EXIT}) → Chrome 再起動して再開: $(date '+%F %T')"
    pkill -f "TikTokCollectorStealth" 2>/dev/null || true
    pkill -f "remote-debugging-port=9222" 2>/dev/null || true
    sleep 5
    "$(dirname "$0")/1_launch_chrome.command" &
    echo "Chrome を再起動中... (最大 30 秒)"
    for _i in $(seq 1 30); do
      sleep 1
      if lsof -nP -iTCP:9222 -sTCP:LISTEN >/dev/null 2>&1; then break; fi
    done
    sleep 5
    echo "=== 再起動: $(date '+%F %T') ==="
    continue
  fi

  # exit 1 (Python 例外)
  CONSEC_ERR1=$((CONSEC_ERR1 + 1))
  if [ "$CONSEC_ERR1" -ge "$MAX_CONSEC_ERR1" ]; then
    echo "exit 1 が ${MAX_CONSEC_ERR1} 回連続しました。設定エラー等の永続障害の可能性があります。停止します。"
    exit 1
  fi
  echo ""
  echo "⚠️  python3 が終了しました(exit ${PY_EXIT}, ${CONSEC_ERR1}/${MAX_CONSEC_ERR1}) → Chrome 再起動して 10 秒後に再開"
  pkill -f "TikTokCollectorStealth" 2>/dev/null || true
  pkill -f "remote-debugging-port=9222" 2>/dev/null || true
  sleep 10
  "$(dirname "$0")/1_launch_chrome.command" &
  echo "Chrome を再起動中... (最大 20 秒)"
  for _i in $(seq 1 20); do
    sleep 1
    if lsof -nP -iTCP:9222 -sTCP:LISTEN >/dev/null 2>&1; then break; fi
  done
  sleep 3
  echo "=== 再起動: $(date '+%F %T') ==="
done
