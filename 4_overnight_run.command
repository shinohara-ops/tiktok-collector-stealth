#!/bin/bash
# 寝てる間ループ用ラッパー。
#
# 動作:
#   1. Chrome が CDP ポート 9222 で見えなければ 1_launch_chrome.command を起動して
#      ポートが開くのを待つ。
#   2. 3_run_collector.command を **非対話モード**(TIKTOK_NONINTERACTIVE=1)で実行。
#      .collector_name / .min_followers / .max_followers は自動で読まれる。
#   3. exit code を見てルーティング:
#        - 77 : フィード詰まり(同じ uid が stuck_full_restart_threshold 連続)
#               → 専用 Chrome(--remote-debugging-port=9222 で動いてるプロセス)
#                 だけを kill → ループ先頭に戻り Chrome 再起動 + main.py 再開
#        - 128+N: シグナル終了(SIGTRAP/SIGABRT/SIGSEGV/SIGKILL/SIGTERM 等)
#               → 専用 Chrome を kill してループ継続(個別列挙不要)
#        - 1  : Python 例外 / 起動失敗 → Chrome kill して再試行。
#               MAX_CONSEC_ERR1 回連続すると停止(設定エラー等の永続障害を検知)
#        - 0  : 正常終了。ラッパーも終了
#        - 130: Ctrl+C。ラッパーも終了
#        - その他: 予期せぬ異常。ラッパーも終了(調査用)
#
# 注意:
#   - .collector_name が無い状態で起動するとエラーで止まる。先に一度
#     3_run_collector.command を対話モードで起動して保存する。
#   - 専用 Chrome 以外の Chrome は kill しない(--remote-debugging-port=9222 文字列で絞る)。
#   - 再起動上限は無い。Ctrl+C で抜けるまでひたすらループする。

set -u
cd "$(dirname "$0")"

export TIKTOK_NONINTERACTIVE=1

# exit code 1 が連続した回数。MAX_CONSEC_ERR1 回連続で永続障害とみなして停止。
CONSEC_ERR1=0
MAX_CONSEC_ERR1=3

cleanup() {
  echo ""
  echo "=== overnight ループを終了します ==="
  exit 0
}
trap cleanup INT TERM

wait_for_chrome() {
  for _ in $(seq 1 40); do
    if lsof -nP -iTCP:9222 -sTCP:LISTEN >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  return 1
}

while true; do
  if ! lsof -nP -iTCP:9222 -sTCP:LISTEN >/dev/null 2>&1; then
    echo "=== Chrome を起動します($(date '+%F %T')) ==="
    "./1_launch_chrome.command" &
    if ! wait_for_chrome; then
      echo "Chrome がポート 9222 で起動しませんでした。中断します。"
      exit 1
    fi
    sleep 5  # TikTok フィードのロードを待つ
  fi

  echo ""
  echo "=== runner 起動: $(date '+%F %T') ==="
  "./3_run_collector.command"
  CODE=$?
  echo "=== runner 終了 (exit $CODE): $(date '+%F %T') ==="

  case "$CODE" in
    77)
      CONSEC_ERR1=0
      echo "stuck → 専用 Chrome を kill して再起動します"
      pkill -f "remote-debugging-port=9222" || true
      sleep 5
      ;;
    1)
      CONSEC_ERR1=$((CONSEC_ERR1 + 1))
      if [ "$CONSEC_ERR1" -ge "$MAX_CONSEC_ERR1" ]; then
        echo "exit 1 が ${MAX_CONSEC_ERR1} 回連続しました。設定エラー等の永続障害の可能性があります。ループを抜けます(調査推奨)"
        exit 1
      fi
      echo "exit 1 (例外 / 起動失敗, ${CONSEC_ERR1}/${MAX_CONSEC_ERR1}) → 専用 Chrome を kill して再起動します"
      pkill -f "remote-debugging-port=9222" || true
      sleep 15
      ;;
    0)
      CONSEC_ERR1=0
      echo "正常終了。ループを抜けます。"
      exit 0
      ;;
    130)
      echo "Ctrl+C で終了。"
      exit 0
      ;;
    *)
      # 128+N はシグナルによる強制終了(SIGTRAP/SIGABRT/SIGKILL/SIGSEGV/SIGTERM 等)。
      # 個別列挙ではなく範囲で捕捉することで、未知のシグナルも自動的に再起動する。
      # 130(Ctrl+C)は上でキャッチ済みなのでここには来ない。
      if [ "$CODE" -ge 128 ] && [ "$CODE" -le 159 ]; then
        echo "シグナル終了 (exit $CODE = signal $((CODE - 128))) → 専用 Chrome を kill して再起動します"
        pkill -f "remote-debugging-port=9222" || true
        sleep 10
      else
        echo "予期せぬ exit code: $CODE → ループを抜けます(調査推奨)"
        exit "$CODE"
      fi
      ;;
  esac
done
