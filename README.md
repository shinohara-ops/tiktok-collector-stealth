# TikTokCollectorStealth

既存 TikTokCollector の **検知耐性版**。実Chrome + CDP接続 + マウスホイール化で
「Wi-Fi #1 だと 3〜4 スワイプでフィードが死ぬ」問題を解消した本体版。

検証フェーズ(probe.py)で 60/60 完走を確認したあと、本体パイプライン
(rules / 黒帯 / AI / Sheets 書込み)もすべて CDP モードに統合済み。

---

## 構成

| ファイル | 役割 |
|---|---|
| `0_setup_mac.command` | 初回セットアップ (venv + Playwright) |
| `1_launch_chrome.command` | 専用プロファイルで実Chromeを起動 (CDPポート 9222) |
| `2_run_probe.command` | 検証ループ(挙動と健康度確認用) |
| `3_run_collector.command` | **本体 collector**(Sheets書込みあり) |
| `probe.py` | 検証用 |
| `main.py` / `src/tiktok_collector/` | 本体パイプライン |
| `data/probe.jsonl` | probe 実行ログ |

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

## 本体 collector の使い方

1. `1_launch_chrome.command` で Chrome を CDP 9222 で起動 → TikTok にログイン → おすすめフィード表示
2. 別ターミナルで `3_run_collector.command`
   - 初回は記入者名(Sheets B列に入る名前)を聞かれる → 入力すると `.collector_name` に保存され、次回からは自動読み込み
   - `.env` の `OPENAI_API_KEY` が必要
3. AI 判定が走り、`recommended` / `blackband` / `pending` / `skipped` のいずれかのタブに追記される

stealth 改造の中身:
- ブラウザ起動を `launch_persistent_context` → `connect_over_cdp` に変更
- スワイプを `ArrowDown` → `mouse.wheel`(失敗時 chevron click)に変更
- 動画ごとに「過去採用 uid + フォロワー < `rules.max_followers`」で候補性を判定し、
  非候補は screenshot/AI を回さず早期 skip
- 候補のうち 5% で `like` を間隔ガード付き(デフォ 90 秒)で発火
- `follow` は実装しない(my-page に痕跡が残る = 検知リスク)

---

## 複数 PC 並行運用

| リソース | 共有/PC別 | 配布方法 |
|---|---|---|
| `credentials/oauth_client.json` | 全PC共通 | 1Password 等で安全配布(git管理外) |
| `credentials/token.json` | **PC ごと別** | 各 PC で初回起動時に OAuth フロー → 自動生成 |
| `.env` (OPENAI_API_KEY) | 全PC共通(同じキーでOK) | 1Password 等で配布 |
| `.collector_name` | **PC ごと別** | `3_run_collector.command` 起動時に対話入力 → 自動生成 |
| Chrome プロファイル | PC ごと別 | `1_launch_chrome.command` が初回作成、TikTokログインも各PCで実施 |
| `data/tiktok_collector.sqlite3` | PC ごと別 | 自動作成 |

### 衝突防止

- **書き込み二重防止**:`sheets.append` は **書き込み直前に Sheets 全タブの uid 列を実 fetch** して dedupe。
  別 PC が直前に同じ uid を書いていれば、こちらの書き込みは `[PRE_APPEND_DUPLICATE_SKIP]` でスキップされる。
- **無駄な AI コール削減**:過去採用 uid マップを `algorithm_stealth.uid_map_refresh_sec`(デフォ 600 秒)
  ごとに Sheets から再取得。別 PC が新規採用した uid はこちら側でも `stealth_candidacy:past_adopted`
  で早期 skip され、AI を回さずに済む。
- **記入者の識別**:Sheets B 列に `.collector_name` の値が入るので、どの PC が書いたかが分かる。

### 推奨運用

- TikTok アカウントは PC ごとに別を用意(同一アカウントを複数 IP で同時操作するとアカウント側で警戒される)
- `.collector_name` は PC が分かる名前にする(例:`篠原-Mac1` / `篠原-Studio` / `篠原-Mini`)
- `1_launch_chrome.command` 起動後の Chrome ウィンドウは閉じない(CDP セッションが切れる)
- ダッシュボード等で進捗を見るときは Sheets の B 列で PC ごとの記入量を集計できる

---

## スナップショットテスト(rules.py の挙動凍結)

`rules.py` の 2233 行に手を入れる前のセーフティネット。Sheets「除外ログ」タブの
実データから 820 ケースを fixture 化し、`local_skip_reason` の戻り値が変わらない
ことを pytest で検証する。

```sh
# 開発用依存をインストール
pip install -r requirements_dev.txt

# テスト実行(~3秒)
pytest tests/test_rules_snapshot.py -q
```

ベースラインの作り直し:

```sh
# Sheets から fixture を採り直す(時間かかる)
python tests/generate_fixtures.py

# 各ケースの expected_reason を現在の rules.py の出力で固定
python tests/rebaseline_fixtures.py
```

意図的に `rules.py` の挙動を変えたとき(条件追加など)はこの 2 つを順に
走らせて fixture を取り直す。意図せず壊した場合は pytest が即落ちる。

---

## 注意

- Chrome ウィンドウは閉じない。閉じると CDP セッションも切れる
- 普段使いの Chrome とは **別プロファイル** (`~/Library/Application Support/TikTokCollectorStealth`)
- 同じポート 9222 が既に使われてると `1_launch_chrome.command` は何もしないで終わる
- `credentials/` と `.env`、`.collector_name` は `.gitignore` 済み。git にコミットされない
