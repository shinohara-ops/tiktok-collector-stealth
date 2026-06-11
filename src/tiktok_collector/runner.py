from __future__ import annotations

import asyncio
import time
from pathlib import Path
from collections import deque
from playwright.async_api import async_playwright
from .scraper import TikTokScraper
from .rules import local_skip_reason, detect_blackband



def _clamp_ai_score_0_10(value):
    try:
        s = str(value).strip()
        if s == "":
            return ""
        num = float(s)
        if num > 10:
            if num <= 100:
                num = num / 10.0
            else:
                num = 10.0
        if num < 0:
            num = 0.0
        if abs(num - round(num)) < 0.0001:
            return str(int(round(num)))
        return str(round(num, 1))
    except Exception:
        return value


class RateLimiter:
    def __init__(self, max_per_minute: int):
        self.max = max(1, int(max_per_minute))
        self.calls = deque()

    async def wait(self):
        now = time.time()
        while self.calls and now - self.calls[0] > 60:
            self.calls.popleft()
        if len(self.calls) >= self.max:
            sleep_for = 60 - (now - self.calls[0]) + 0.1
            await asyncio.sleep(max(0.1, sleep_for))
        self.calls.append(time.time())








async def _start_pause_guard(page):
    """
    判定前の一時停止用。TikTokが再生を再開しても250msごとに止める。
    対象になった時だけ _watch_complete_and_visit_profile 内で解除して再生する。
    """
    try:
        await page.evaluate("""
        () => {
          if (window.__tiktokPauseGuardMinimal) return;
          window.__tiktokPauseGuardMinimal = setInterval(() => {
            try {
              const vw = innerWidth, vh = innerHeight;
              const videos = Array.from(document.querySelectorAll('video'))
                .map(v => {
                  const r = v.getBoundingClientRect();
                  const visibleW = Math.max(0, Math.min(r.right, vw) - Math.max(r.left, 0));
                  const visibleH = Math.max(0, Math.min(r.bottom, vh) - Math.max(r.top, 0));
                  return {video: v, area: visibleW * visibleH};
                })
                .filter(x => x.area > 5000)
                .sort((a,b) => b.area - a.area);
              const v = videos[0]?.video;
              if (v && !v.paused) v.pause();
            } catch(e) {}
          }, 250);
        }
        """)
    except Exception:
        pass


async def _stop_pause_guard(page):
    try:
        await page.evaluate("""
        () => {
          if (window.__tiktokPauseGuardMinimal) {
            clearInterval(window.__tiktokPauseGuardMinimal);
            window.__tiktokPauseGuardMinimal = null;
          }
          if (window.__tiktokPauseGuard) {
            clearInterval(window.__tiktokPauseGuard);
            window.__tiktokPauseGuard = null;
          }
          if (window.__warmupPauseGuard) {
            clearInterval(window.__warmupPauseGuard);
            window.__warmupPauseGuard = null;
          }
        }
        """)
    except Exception:
        pass


async def _watch_complete_and_visit_profile(page, candidate=None):
    """
    本番安定版:
    おすすめ候補だけ再生して視聴する。
    プロフィールページは開かない。
    """
    import asyncio

    await _stop_pause_guard(page)

    async def _watch_seconds():
        try:
            data = await page.evaluate("""
            () => {
              const vw = innerWidth, vh = innerHeight;
              const videos = Array.from(document.querySelectorAll('video'))
                .map(v => {
                  const r = v.getBoundingClientRect();
                  const visibleW = Math.max(0, Math.min(r.right, vw) - Math.max(r.left, 0));
                  const visibleH = Math.max(0, Math.min(r.bottom, vh) - Math.max(r.top, 0));
                  return {
                    duration: Number(v.duration || 0),
                    currentTime: Number(v.currentTime || 0),
                    area: visibleW * visibleH
                  };
                })
                .filter(x => x.area > 5000 && Number.isFinite(x.duration) && x.duration > 0);
              if (!videos.length) return null;
              videos.sort((a,b) => b.area - a.area);
              return videos[0];
            }
            """)
            if not data:
                return 18
            duration = float(data.get("duration") or 0)
            current = float(data.get("currentTime") or 0)
            if duration <= 0 or duration > 45:
                return 22
            remain = duration - current
            if remain <= 0:
                return 5
            return max(8, min(26, int(remain) + 3))
        except Exception:
            return 18

    async def _play_current_video():
        try:
            await page.evaluate("""
            () => {
              const vw = innerWidth, vh = innerHeight;
              const videos = Array.from(document.querySelectorAll('video'))
                .map(v => {
                  const r = v.getBoundingClientRect();
                  const visibleW = Math.max(0, Math.min(r.right, vw) - Math.max(r.left, 0));
                  const visibleH = Math.max(0, Math.min(r.bottom, vh) - Math.max(r.top, 0));
                  return {video: v, area: visibleW * visibleH};
                })
                .filter(x => x.area > 5000)
                .sort((a,b) => b.area - a.area);
              const v = videos[0]?.video;
              if (v && v.paused) v.play().catch(() => {});
            }
            """)
        except Exception:
            pass

    wait_sec = await _watch_seconds()
    print(f"おすすめ候補のため視聴します... {wait_sec}秒", flush=True)
    await _play_current_video()
    await asyncio.sleep(wait_sec)

    # 次の判定に備えて、再度止める
    await _start_pause_guard(page)




async def _same_id_recovery_guard(page, candidate=None):
    import asyncio

    def _uid(obj):
        try:
            if obj is None:
                return ""
            if isinstance(obj, dict):
                return str(obj.get("unique_id", "") or obj.get("user_id", "") or obj.get("id", "") or "")
            return str(getattr(obj, "unique_id", "") or getattr(obj, "user_id", "") or getattr(obj, "id", "") or "")
        except Exception:
            return ""

    uid = _uid(candidate).strip()
    if not uid:
        return False

    try:
        last_uid = getattr(page, "_same_id_guard_last_uid", "")
        count = int(getattr(page, "_same_id_guard_count", 0) or 0)

        if uid == last_uid:
            count += 1
        else:
            count = 1

        setattr(page, "_same_id_guard_last_uid", uid)
        setattr(page, "_same_id_guard_count", count)

        if count < 3:
            return False

        print(f"同じIDが3回続いたため復旧します: {uid}", flush=True)
        setattr(page, "_same_id_guard_count", 0)

        try:
            try:
                await _stop_pause_guard(page)
            except Exception:
                pass
            for _ in range(3):
                await page.keyboard.press("ArrowDown")
                await asyncio.sleep(0.8)
        except Exception as e:
            print(f"同一ID復旧スワイプでエラー: {str(e)[:120]}", flush=True)

        try:
            print("同一ID復旧のためTikTokをリロードします", flush=True)
            try:
                setattr(page, "_follower_count_cache", {})
            except Exception:
                pass
            await page.goto("https://www.tiktok.com/", wait_until="domcontentloaded", timeout=20000)
            await page.wait_for_timeout(4000)
            try:
                await page.keyboard.press("ArrowDown")
                await page.wait_for_timeout(1000)
            except Exception:
                pass
        except Exception as e:
            print(f"同一ID復旧リロードでエラー: {str(e)[:120]}", flush=True)

        return True
    except Exception as e:
        print(f"同一IDガードでエラー: {str(e)[:120]}", flush=True)
        return False





async def _repair_candidate_profile_and_hashtags(page, candidate, scraper=None):
    """
    シート記入/ローカル判定の直前に、プロフィール紹介文とハッシュタグを補完する。
    プロフィールページは開かない。
    """
    import re

    def _getv(obj, *names):
        for name in names:
            try:
                if isinstance(obj, dict):
                    v = obj.get(name)
                else:
                    v = getattr(obj, name, None)
                if v is not None and str(v).strip() != "":
                    return v
            except Exception:
                pass
        return ""

    def _setv(obj, name, value):
        value = str(value or "").strip()
        if not value:
            return
        try:
            setattr(obj, name, value)
        except Exception:
            try:
                object.__setattr__(obj, name, value)
            except Exception:
                pass

    uid = str(_getv(candidate, "unique_id", "user_id", "id")).strip()

    profile_text = str(_getv(candidate, "signature", "bio", "profile_bio", "profile_text", "description", "desc")).strip()
    if not profile_text and scraper is not None:
        try:
            got = await scraper.detect_profile_text_from_feed(page, uid)
            if isinstance(got, tuple):
                profile_text = str(got[0] or "").strip()
            else:
                profile_text = str(got or "").strip()
        except Exception as e:
            print(f"プロフィール紹介文補完エラー: {str(e)[:120]}", flush=True)

    if profile_text:
        for key in ["signature", "bio", "profile_bio", "profile_text"]:
            _setv(candidate, key, profile_text)

    hashtags_raw = _getv(candidate, "hashtags", "hashtag", "tags", "tag_text", "hashtag_text")
    if isinstance(hashtags_raw, (list, tuple, set)):
        hashtags_text = " ".join([str(x).lstrip("#") for x in hashtags_raw if str(x).strip()])
    else:
        hashtags_text = str(hashtags_raw or "").strip()

    if not hashtags_text:
        base_text = " ".join([
            str(_getv(candidate, "caption", "title", "text", "body", "video_desc")),
            str(_getv(candidate, "desc", "description")),
            str(_getv(candidate, "signature", "bio", "profile_bio", "profile_text")),
        ])
        found = re.findall(r"#([A-Za-z0-9_ぁ-んァ-ン一-龥ー]+)", base_text)
        if found:
            hashtags_text = " ".join(dict.fromkeys(found[:12]))

    if not hashtags_text:
        try:
            dom_text = await page.locator("body").inner_text(timeout=2500)
            found = re.findall(r"#([A-Za-z0-9_ぁ-んァ-ン一-龥ー]+)", dom_text or "")
            ng = {"おすすめ", "フォロー中", "LIVE", "ライブ", "検索"}
            found = [x for x in found if x not in ng]
            if found:
                hashtags_text = " ".join(dict.fromkeys(found[:12]))
        except Exception:
            pass

    if hashtags_text:
        for key in ["hashtags", "hashtag_text", "tag_text"]:
            _setv(candidate, key, hashtags_text)

    return candidate


class TikTokRunner:
    def __init__(self, cfg, db, sheets, notifier, ai):
        self.cfg = cfg
        self.db = db
        self.sheets = sheets
        self.notifier = notifier
        self.ai = ai
        self.scraper = TikTokScraper(cfg.logging.screenshot_dir)
        self.rate = RateLimiter(cfg.rate.max_ai_calls_per_minute)
        self.processed_count = 0
        self.written_count = 0
        self.last_health = time.time()
        self.sheet_seen_ids = set()
        self.sheet_status_by_id = {}

    def _stop_requested(self) -> bool:
        return Path("data/STOP_REQUESTED").exists()

    def _clear_stop_requested(self):
        try:
            Path("data/STOP_REQUESTED").unlink()
        except FileNotFoundError:
            pass

    async def _watch_target_video(self, page):
        sec = int(getattr(getattr(self.cfg, "algorithm", None), "watch_target_sec", 12) or 12)
        sec = max(5, min(sec, 20))
        await _watch_complete_and_visit_profile(page, locals().get('candidate'))
        try:
            await page.evaluate("""() => {
              const v = Array.from(document.querySelectorAll('video')).find(v => {
                const r = v.getBoundingClientRect();
                return r.width > 120 && r.height > 180;
              });
              if (v) { v.muted = true; v.play().catch(() => {}); }
            }""")
        except Exception:
            pass
        await asyncio.sleep(sec)

    async def run(self):
        self._clear_stop_requested()
        self.notifier.send("TikTok Collector 起動")
        start_ts = time.time()

        try:
            if hasattr(self.sheets, "get_unique_id_status_map"):
                self.sheet_status_by_id = self.sheets.get_unique_id_status_map()
                self.sheet_seen_ids = set(self.sheet_status_by_id.keys())
            else:
                self.sheet_seen_ids = self.sheets.get_all_unique_ids()
                self.sheet_status_by_id = {uid: "seen" for uid in self.sheet_seen_ids}
            print(f"過去記載済みIDを読み込みました: {len(self.sheet_seen_ids)}件", flush=True)
        except Exception as e:
            print(f"過去記載済みIDの読み込みに失敗: {e}", flush=True)
            self.sheet_seen_ids = set()
            self.sheet_status_by_id = {}

        async with async_playwright() as p:
            print("Playwright起動OK。専用Chromeプロファイルを開きます...", flush=True)
            context = await p.chromium.launch_persistent_context(
                user_data_dir=self.cfg.browser.user_data_dir,
                headless=self.cfg.browser.headless,
                viewport={"width": self.cfg.browser.viewport_width, "height": self.cfg.browser.viewport_height},
                args=["--disable-blink-features=AutomationControlled", "--no-first-run", "--disable-dev-shm-usage"],
            )
            page = context.pages[0] if context.pages else await context.new_page()
            print("専用Chromeを開きました。TikTokへ移動します...", flush=True)
            try:
                try:
                    self.scraper.attach_follower_response_cache(page)
                except Exception:
                    pass

                await page.goto(self.cfg.browser.start_url, wait_until="domcontentloaded", timeout=20000)
            except Exception as e:
                print("TikTokの自動遷移でエラーが出ましたが、処理は止めません。", flush=True)
                print("Chromeが開いている場合は、アドレスバーに https://www.tiktok.com/ を手入力してください。", flush=True)
                print("おすすめフィードが表示されたら、この黒い画面に戻ってEnterを押してください。", flush=True)
                print(f"遷移エラー: {str(e)[:180]}", flush=True)
                try:
                    await page.goto("about:blank", wait_until="domcontentloaded", timeout=5000)
                except Exception:
                    pass
                await asyncio.to_thread(input, "TikTokおすすめフィードを表示したらEnter: ")
            print("TikTokを開きました。ログインが必要なら手動でログインしてください。", flush=True)
            await asyncio.sleep(self.cfg.browser.startup_wait_sec)

            while True:
                if (time.time() - start_ts) > self.cfg.browser.max_runtime_minutes * 60:
                    self.notifier.send("最大稼働時間に到達したため停止")
                    break

                try:
                    await asyncio.wait_for(self._process_one(page), timeout=90)
                except asyncio.TimeoutError:
                    print("1投稿の処理が90秒を超えたため次へ進みます。", flush=True)
                except Exception as e:
                    print(f"処理エラー: {str(e)[:160]}", flush=True)

                self.processed_count += 1

                if self._stop_requested():
                    print("安全停止要求を検知しました。停止します。", flush=True)
                    self.notifier.send("TikTok Collector 安全停止")
                    self._clear_stop_requested()
                    break

                if self.processed_count % self.cfg.rate.rest_every_n_posts == 0:
                    await asyncio.sleep(self.cfg.rate.rest_sec)

                if time.time() - self.last_health > 1800:
                    self.notifier.send(f"稼働中: processed={self.processed_count}, written={self.written_count}")
                    self.last_health = time.time()

                await self.scraper.next_post(page)
                await asyncio.sleep(self.cfg.browser.action_delay_sec)

            await context.close()


    def _negative_feedback_enabled(self) -> bool:
        cfg = getattr(self.cfg, "algorithm_feedback", None)
        if cfg is None:
            return True
        return bool(getattr(cfg, "enable_negative_feedback_for_excluded", True))

    def _negative_feedback_min_interval_sec(self) -> int:
        cfg = getattr(self.cfg, "algorithm_feedback", None)
        if cfg is None:
            return 20
        try:
            return int(getattr(cfg, "negative_feedback_min_interval_sec", 20) or 20)
        except Exception:
            return 20

    def _negative_feedback_rate_limited(self):
        import time
        interval = max(0, self._negative_feedback_min_interval_sec())
        last = float(getattr(self, "_last_negative_feedback_at", 0.0) or 0.0)
        now = time.time()
        remaining = interval - (now - last)
        return remaining > 0, max(0.0, remaining)

    def _mark_negative_feedback_rate(self):
        import time
        setattr(self, "_last_negative_feedback_at", time.time())

    def _is_excluded_status(self, status: str) -> bool:
        return str(status or "").strip().lower() in {"skipped", "skipped_ai", "excluded", "exclude", "local_excluded", "ai_excluded"}

    async def _force_advance_after_skip(self, page, uid: str = ""):
        """
        スキップ/処理済み/興味なし対象外のとき、同じ動画に張り付かないよう強制的に次へ進める。
        """
        for method in range(1, 7):
            try:
                if method == 1:
                    try:
                        await self.scraper.next_video(page)
                    except TypeError:
                        await self.scraper.next_video()
                elif method == 2:
                    await page.keyboard.press("ArrowDown")
                elif method == 3:
                    await page.keyboard.press("PageDown")
                elif method == 4:
                    await page.keyboard.press("j")
                elif method == 5:
                    await page.mouse.wheel(0, 900)
                elif method == 6:
                    await page.evaluate("window.scrollBy(0, Math.max(700, window.innerHeight * 0.85))")
                await page.wait_for_timeout(900)
                return True
            except Exception:
                continue
        print(f"[FORCE_ADVANCE_AFTER_SKIP_FAILED] account_id={uid}", flush=True)
        return False

    def _is_allowed_negative_feedback_target(self, status: str, reason: str = "") -> bool:
        """
        TikTokの「興味なし」を押す対象を、明確NGカテゴリだけに限定する。
        ローカル除外自体は維持するが、ここに該当しない除外理由では興味なしを押さない。
        """
        import re

        r = str(reason or "").strip().lower()
        if not r:
            return False

        blocked_keywords = [
            "フォロワー数", "フォロワー数ng", "フォロワー数未取得", "フォロワー",
            "follower", "followers", "follow_count", "follower_count",
            "フォロー中", "フォロー状態不明",
            "プロフィール紹介文空欄", "プロフィール空欄", "ハッシュタグ/プロフィール紹介文空欄",
            "プロフィール紹介文が絵文字のみ", "既に記入", "記入済み", "シート重複",
            "duplicate", "already", "過去除外", "興味なし済み", "feedback_done",
        ]
        if any(k.lower() in r for k in blocked_keywords):
            return False

        allowed_keywords = [
            "id形式ng", "user始まり",
            "08", "09", "10line", "11line", "12line", "13line", "14line", "15line",
            "08line", "09line", "2008", "2009", "2010", "2011", "2012",
            "jk", "jc", "js", "fjk", "sjk", "ljk", "高校生", "中学生", "通信制高校", "受験生",
            "13歳", "14歳", "15歳", "16歳", "17歳", "13才", "14才", "15才", "16才", "17才",
            "13さい", "14さい", "15さい", "16さい", "17さい", "11y", "12y", "13y", "14y", "15y", "16y", "17y",
            "文化祭", "体育祭", "修学旅行", "高一", "高二", "中一", "中二", "中三",
            "海外", "外国語", "外国人", "韓国語", "タイ語", "ベトナム語", "ロシア語",
            "ネパール語", "クメール語", "アラビア語", "ミャンマー語", "ラオ語",
            "中国語", "簡体字", "繁体字", "英語文章bio", "韓国語文章bio",
            "ベトナム語アクセント", "korea", "korean", "china", "chinese",
            "thai", "vietnam", "indonesia", "malaysia", "singapore", "overseas", "foreign",
            "xuhuong", "gaixinh", "xinhdep", "cewek", "wanita", "cantik", "mencari", "jakarta",
            "follow tui", "1000fl", "台湾", "香港", "台灣", "hong kong", "中文", "華語",
            "ランダムid/海外", "海外・量産",
            "所属", "事務所所属", "ライバー事務所", "公式ライバー", "認証ライバー",
            "seju", "asobinext", "vaz", "grove", "avex", "studio15", "321inc", "nextwave", "pococha", "17live", "palmu",
            "配信者", "ライバー", "ライブ配信", "live配信", "配信垢", "配信中", "初見歓迎", "ファンマ", "推し活", "フォロバ", "相互フォロー",
            "歌詞動画", "歌詞", "lyrics", "弾き語り", "歌ってみた", "cover", "mv", "pv", "切り抜き", "転載", "拾い画", "拾い動画", "外部映像",
            "ライブ映像", "ステージ", "マイク", "ピンマイク", "アイドル", "地下アイドル", "芸能人", "女優", "俳優", "ファンアカウント",
            "坂道", "akb", "k-pop", "kpop", "イコラブ", "ノイミー", "ニアジョイ", "fruits zipper",
            "企業", "公式", "広告", "pr", "認証", "青チェック", "会社", "株式会社", "店舗", "shop", "store", "brand",
            "ゲーム", "ゲーム実況", "apex", "荒野行動", "原神", "ポケモン", "スプラ", "プロセカ", "フォートナイト", "minecraft", "valorant", "モンスト",
            "アニメ", "漫画", "マンガ", "声優", "コスプレ", "レイヤー", "ホロライブ", "エヴァ", "gta", "gaming",
            "猫", "犬", "ハムスター", "うさぎ", "ペット", "動物", "ハリネズミ", "柴犬", "ラーメン", "カレー", "グルメ", "飯テロ", "食べ歩き",
            "自炊", "レシピ", "スイーツ", "ランチ", "ディナー", "焼肉", "寿司", "カフェ巡り", "料理", "料理動画",
            "えち", "えっち", "エロ", "裏垢", "セフレ", "オフパコ", "抜ける", "下着", "ランジェリー", "パンチラ", "谷間", "おっぱい", "巨乳",
            "尻", "太もも", "フェチ", "fetish", "sexy", "セクシー", "mature", "lingerie", "beauty系", "glam", "女装", "男の娘", "偽娘", "ニューハーフ",
        ]
        if any(k.lower() in r for k in allowed_keywords):
            return True

        age_patterns = [r"\b0?[8-9]\b", r"\b1[0-5]\b", r"\b20(08|09|10|11|12)\b", r"#0?[89]", r"\((1[1-7])\)"]
        if any(re.search(pat, r) for pat in age_patterns):
            return True

        return False

    async def _negative_feedback_for_current_exclusion(self, page, candidate, status: str, reason: str = "") -> bool:
        """
        ローカル除外/AI除外になったその場で、reason付きで興味なし判定する。
        既処理DB経由だとreasonが空になるため、ここで直接判定する。
        """
        uid = str(getattr(candidate, "unique_id", "") or "").strip()
        if not uid:
            return False
        reason = str(reason or "").strip()

        if not self._negative_feedback_enabled():
            return False

        if not self._is_allowed_negative_feedback_target(status, reason):
            print(f"[SKIP_NEGATIVE_FEEDBACK_NOT_LOCAL_OR_AI] account_id={uid} status={status} reason={reason}", flush=True)
            return False

        try:
            processed = self.db.get(uid)
            already_done = bool(int((processed or {}).get("negative_feedback_done") or 0))
        except Exception:
            already_done = False
        if already_done:
            print(f"[SKIP_EXCLUDED_FEEDBACK_DONE] account_id={uid}", flush=True)
            return False

        try:
            limited, remaining = self._negative_feedback_rate_limited()
        except Exception:
            limited, remaining = False, 0
        if limited:
            try:
                wait_for = max(0.0, float(remaining))
            except Exception:
                wait_for = 0.0
            print(f"[SKIP_EXCLUDED_FEEDBACK_RATE_LIMIT] account_id={uid} wait_sec={wait_for:.1f}", flush=True)
            return False

        print(f"[NEGATIVE_FEEDBACK_TARGET_CONFIRMED] account_id={uid} status={status} reason={reason}", flush=True)
        print(f"[NEGATIVE_FEEDBACK_EXCLUDED_START] account_id={uid}", flush=True)
        try:
            ok, err_reason = await self.scraper.mark_not_interested_current(page)
        except Exception as e:
            ok, err_reason = False, str(e)[:200]

        if ok:
            print(f"[NEGATIVE_FEEDBACK_EXCLUDED_SUCCESS] account_id={uid}", flush=True)
            try:
                self._mark_negative_feedback_rate()
                self.db.mark_negative_feedback_success(uid)
                self.db.event("info", f"negative_feedback_success: {reason}", uid)
            except Exception:
                pass
            return True

        print(f"[NEGATIVE_FEEDBACK_EXCLUDED_FAILED] account_id={uid} reason={err_reason}", flush=True)
        try:
            failed = getattr(self, "_negative_feedback_failed_ids", set())
            failed.add(uid)
            setattr(self, "_negative_feedback_failed_ids", failed)
            self.db.mark_negative_feedback_error(uid, err_reason)
            self.db.event("warn", f"negative_feedback_failed: {err_reason}", uid)
        except Exception:
            pass
        return False

    async def _handle_already_processed_candidate(self, page, candidate, processed: dict | None = None) -> bool:
        """
        既処理IDは原則スキップ。過去除外には興味なしを押さない。
        興味なしは、今その場でローカル除外/AI除外になったものだけ reason 付きで判定する。
        """
        uid = str(getattr(candidate, "unique_id", "") or "").strip()
        if not uid:
            return False
        if processed is None:
            processed = self.db.get(uid)
        status = str((processed or {}).get("status") or self.sheet_status_by_id.get(uid, "") or "")
        if status == "recommended":
            print(f"[SKIP_RECOMMENDED_ALREADY_PROCESSED] account_id={uid}", flush=True)
            try:
                self.db.touch_seen(uid)
            except Exception:
                pass
            await self._force_advance_after_skip(page, uid)
            return True
        if self._is_excluded_status(status):
            reason = str((processed or {}).get("reason") or "")
            print(f"[SKIP_NEGATIVE_FEEDBACK_NOT_LOCAL_OR_AI] account_id={uid} status={status} reason={reason}", flush=True)
            try:
                self.db.touch_seen(uid)
            except Exception:
                pass
            await self._force_advance_after_skip(page, uid)
            return True
        if status:
            print(f"既処理スキップ: {uid} / status={status}", flush=True)
            try:
                self.db.touch_seen(uid)
            except Exception:
                pass
            await self._force_advance_after_skip(page, uid)
            return True
        return False

    async def _process_one(self, page):
        candidate = await self.scraper.current_candidate(page)
        if not candidate:
            self.db.event("warn", "candidate取得失敗")
            return

        processed = self.db.get(candidate.unique_id)
        if processed:
            if await self._handle_already_processed_candidate(page, candidate, processed):
                return

        if candidate.unique_id in self.sheet_seen_ids:
            if await self._handle_already_processed_candidate(page, candidate, None):
                return
            print(f"既処理スキップ: {candidate.unique_id}", flush=True)
            await self._force_advance_after_skip(page, candidate.unique_id)
            return

        follow_state = await self.scraper.detect_follow_state_local(page)
        if follow_state == "following":
            reason = "フォロー中"
            print(f"ローカル除外: {candidate.unique_id} / {reason}", flush=True)
            self.db.mark(candidate.unique_id, "skipped", reason, candidate.profile_url, candidate.post_url, "")
            self.sheets.append("skipped", candidate.to_row(self.cfg.collector_name, reason=reason, model_used="local:check-path"))
            self.sheet_seen_ids.add(candidate.unique_id)
            await self._negative_feedback_for_current_exclusion(page, candidate, "skipped", reason)
            return

        if follow_state != "not_following":
            reason = "フォロー状態不明"
            print(f"ローカル除外: {candidate.unique_id} / {reason}", flush=True)
            self.db.mark(candidate.unique_id, "skipped", reason, candidate.profile_url, candidate.post_url, "")
            self.sheets.append("skipped", candidate.to_row(self.cfg.collector_name, reason=reason, model_used="local:follow-unknown"))
            self.sheet_seen_ids.add(candidate.unique_id)
            await self._negative_feedback_for_current_exclusion(page, candidate, "skipped", reason)
            return


        # フォロワー数取得。プロフィールページは開かない。取得後は local_skip_reason が既存ルールで判定する。

        try:

            follower_count, follower_source = await self.scraper.detect_follower_count_from_feed(page, candidate.unique_id)

        except Exception:

            follower_count, follower_source = None, ""


        try:

            object.__setattr__(candidate, "follower_count", follower_count if follower_count is not None else "")

            object.__setattr__(candidate, "follower_source", follower_source or "")

        except Exception:

            pass



        # プロフィール紹介文取得。プロフィールページは開かない。


        try:


            profile_text, profile_source = await self.scraper.detect_profile_text_from_feed(page, candidate.unique_id)


        except Exception:


            profile_text, profile_source = "", ""



        if profile_text:


            try:


                object.__setattr__(candidate, "signature", profile_text)


                object.__setattr__(candidate, "bio", profile_text)


                object.__setattr__(candidate, "profile_text_source", profile_source or "")


            except Exception:


                pass



        # minimal pause before judgement: 判定前に動画を停止し、対象外視聴を増やさない



        await _start_pause_guard(page)



        # profile/hashtag repair before local rules
        try:
            candidate = await _repair_candidate_profile_and_hashtags(page, candidate, getattr(self, "scraper", None))
        except Exception as e:
            print(f"profile/hashtag repair error: {str(e)[:120]}", flush=True)
        reason = local_skip_reason(candidate, self.cfg.rules)
        if reason:
            print(f"ローカル除外: {candidate.unique_id} / {reason}", flush=True)
            self.db.mark(candidate.unique_id, "skipped", reason, candidate.profile_url, candidate.post_url, "")
            self.sheets.append("skipped", candidate.to_row(self.cfg.collector_name, reason=reason, model_used="local:no-screenshot"))
            self.sheet_seen_ids.add(candidate.unique_id)
            await self._negative_feedback_for_current_exclusion(page, candidate, "skipped", reason)
            return

        screenshot_path = await self.scraper.screenshot_current(page, candidate.unique_id)
        candidate.screenshot_path = screenshot_path

        is_blackband = detect_blackband(
            screenshot_path,
            self.cfg.blackband.top_bottom_dark_ratio_threshold,
            self.cfg.blackband.dark_pixel_threshold,
        )
        candidate.blackband = is_blackband
        if is_blackband and not self.cfg.blackband.send_to_ai:
            reason = "黒帯検出"
            print(f"黒帯確認: {candidate.unique_id}", flush=True)
            self.db.mark(candidate.unique_id, "blackband", reason, candidate.profile_url, candidate.post_url, screenshot_path)
            self.sheets.append("blackband", candidate.to_row(self.cfg.collector_name, reason=reason, model_used="local:blackband"))
            self.sheet_seen_ids.add(candidate.unique_id)
            return

        await self.rate.wait()
        try:
            result = self.ai.judge_with_fallback_if_needed(screenshot_path, candidate.dict())
            if isinstance(result, dict) and "cute_score" in result:
                result["cute_score"] = _clamp_ai_score_0_10(result.get("cute_score", ""))
        except Exception as e:
            reason = "AI未判定/保留: " + str(e)[:120]
            print(f"AI保留: {candidate.unique_id} / {reason}", flush=True)
            self.db.mark(candidate.unique_id, "pending", reason, candidate.profile_url, candidate.post_url, screenshot_path)
            self.sheets.append("pending", candidate.to_row(self.cfg.collector_name, reason=reason, model_used="pending:no-ai"))
            self.sheet_seen_ids.add(candidate.unique_id)
            return

        if result.get("target"):
            score = str(result.get("cute_score", ""))
            reason = str(result.get("reason", ""))
            model_used = str(result.get("model_used", ""))
            # profile/hashtag repair before recommend write
            try:
                candidate = await _repair_candidate_profile_and_hashtags(page, candidate, getattr(self, "scraper", None))
            except Exception as e:
                print(f"profile/hashtag repair error: {str(e)[:120]}", flush=True)
            print(f"おすすめ記入: {candidate.unique_id}", flush=True)
            self.db.mark(candidate.unique_id, "recommended", reason, candidate.profile_url, candidate.post_url, screenshot_path)
            self.sheets.append("recommended", candidate.to_row(self.cfg.collector_name, reason=reason, score=score, model_used=model_used))
            self.sheet_seen_ids.add(candidate.unique_id)
            self.written_count += 1
            await self._watch_target_video(page)
        else:
            reason = str(result.get("reason", "AI除外"))
            model_used = str(result.get("model_used", ""))
            print(f"AI除外: {candidate.unique_id} / {reason}", flush=True)
            self.db.mark(candidate.unique_id, "skipped_ai", reason, candidate.profile_url, candidate.post_url, screenshot_path)
            self.sheets.append("skipped", candidate.to_row(self.cfg.collector_name, reason=reason, score=str(result.get("cute_score", "")), model_used=model_used))
            self.sheet_seen_ids.add(candidate.unique_id)
            await self._negative_feedback_for_current_exclusion(page, candidate, "skipped_ai", reason)

