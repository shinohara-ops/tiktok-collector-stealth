# TikTokCollectorStealth (検証フェーズ)

既存 TikTokCollector が「Wi-Fi #1だと 3〜4スワイプでフィードが死ぬ」問題を、
**実Chrome+CDP接続+マウスホイール化** で回避できるか確認するための最小検証ツール。

判定ロジック (rules / AI / Sheets) はまだ載せていない。
**まずフィードが生き続けるかどうか**を確かめてから載せる。

---

## 構成

| ファイル | 役割 |
|---|---|
| `0_setup_mac.command` | 初回セットアップ (venv + Playwright) |
| `1_launch_chrome.command` | 専用プロファイルで実Chromeを起動 (CDPポート 9222) |
| `2_run_probe.command` | Pythonで CDP に接続して検証ループ |
| `probe.py` | 本体 |
| `data/probe.jsonl` | 実行ログ (1スワイプ1行) |

---

## 使い方

### 初回

1. `0_setup_mac.command` をダブルクリック
   - venv 作成、playwright インストール
2. `1_launch_chrome.command` をダブルクリック
   - 専用Chromeが起動し、TikTokが開く
   - **手動でTikTokにログイン**(初回のみ)
   - おすすめフィードが見える状態にする
3. ミッションコントロール (F3) で新Spaceを作り、このChromeウィンドウを移動
4. 別のFinderから `2_run_probe.command` をダブルクリック
   - デフォルト60スワイプ
   - 回数指定したい場合はターミナルで `./2_run_probe.command 200`

### 2回目以降

1. `1_launch_chrome.command` → Chrome起動 (ログイン状態は維持される)
2. 別Spaceへ移動
3. `2_run_probe.command` で検証ループ

---

## 結果の見方

`data/probe.jsonl` は1行1イベントのJSON。重要フィールド:

- `before_uid` / `after_uid` … スワイプ前後の作者ID
- `same_uid_streak` … 連続して同じIDが続いた回数
- `playing` … 動画が再生中か
- `event: warn_feed_stuck` … 同じIDが3連続以上→フィード詰まりの疑い

### 健康なフィード
```
swipe i=1  before=userA after=userB streak=0
swipe i=2  before=userB after=userC streak=0
swipe i=3  before=userC after=userD streak=0
```

### 検知された(詰まった)
```
swipe i=4  before=userD after=userD streak=1
swipe i=5  before=userD after=userD streak=2
warn_feed_stuck
```

---

## 検証ステップ

1. **Wi-Fi #2 (無傷側) で probe 60回**
   - 期待: streakがほぼ0、warn_feed_stuck が出ない
   - もし stuck が出るなら、stealth/挙動側に追加対策が必要
2. **Wi-Fi #1 (汚染側) で probe 60回**
   - 既存ツールでは 3〜4スワイプで死んでた
   - ここで 30回以上生き残れば、CDP方式+マウスホイール化の効果あり
   - すぐ死ぬなら、行動より IP 側の影響が強い → ネットワーク対策が必要

---

## 注意

- このChromeウィンドウは閉じない。閉じるとCDPセッションも切れる
- 普段使いのChromeとは**別プロファイル** (`~/Library/Application Support/TikTokCollectorStealth`)
- 同じポート9222 が既に使われてると `1_launch_chrome.command` は何もしないで終わる
