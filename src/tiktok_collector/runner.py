from __future__ import annotations

import asyncio
import random
import time
from pathlib import Path
from collections import deque
from playwright.async_api import async_playwright
from .scraper import TikTokScraper
from .rules import local_skip_reason, detect_blackband
from ._stealth import STEALTH_INIT_JS, fire_like as _stealth_fire_like


# ローカルルールで弾かれた reason のうち、AI 画像判定にバトンタッチするべき
# heuristic 系の prefix。uid + テキストだけの判定は誤検出が多いので、AI に画像で
# 本人らしさを確認させる方が正確。確証性が高い NG(未成年系 / 外部リンク /
# 類似除外 / フォロワー数 等)は引き続き早期スキップする。
# 新規候補にも 過去除外 uid の再判定にも同じ集合を適用する。
_AI_OVERRIDE_LOCAL_REASON_PREFIXES: tuple[str, ...] = (
    "ランダムID",
    "外国語/海外(",
)


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
    """**stealth モードでは何もしない**(完全 noop)。

    元 collector は判定中に動画を一時停止して「視聴時間を増やさない」設計だったが、
    stealth では下記の理由で pause を一切しない方針:
      1. 普通のユーザーは動画を能動的に一時停止しない。pause を呼ぶこと自体が
         anti-bot 検知の材料になり得る(video element の pause() 呼び出しパターン)
      2. 画面上で再生/一時停止アイコンが点滅して明らかに不自然(ユーザー報告)
      3. 視聴時間制御は別経路で達成済み:
         - target=False → 短く再生 → スワイプ(自然な「興味なし」挙動)
         - target=True → _watch_target_video で動画完視聴(complete view シグナル)

    関数は signature を残したまま中身を空にして、call site の変更を最小化。"""
    return


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
        # stealth like の状態
        self._last_like_ts = 0.0
        self._liked_uids: set[str] = set()
        # 過去採用 uid マップ refresh 用
        self._uid_map_last_refresh_ts = 0.0
        # フィード詰まり検出(同じ uid 連続)+ Chrome reload による復帰
        self._last_seen_uid = ""
        self._same_uid_streak = 0
        self._reload_count = 0
        # 過去除外 uid の再判定は 1 セッション 1 uid 1 回だけ。
        # 既処理が増えてくると同じ uid が何度も流れてくるので、毎回 AI 叩くと
        # コストが爆発するうえに、結局再除外で時間を浪費するだけになる。
        self._past_excluded_rechecked: set[str] = set()

    def _maybe_refresh_uid_map(self) -> None:
        """過去採用 uid マップを定期的に Sheets から再取得する。
        複数 PC 運用時、別 PC が新規採用した uid をこの PC の早期 skip にも乗せる。
        書き込み二重防止は別途 _fresh_existing_uids_all_tabs が担保しているので、
        ここは「無駄に AI を回さない」最適化目的。失敗時は静かに継続。
        """
        algo_st = getattr(self.cfg, "algorithm_stealth", None)
        interval = float(getattr(algo_st, "uid_map_refresh_sec", 600.0) or 600.0)
        if interval <= 0:
            return
        now = time.time()
        if (now - self._uid_map_last_refresh_ts) < interval:
            return
        if not hasattr(self.sheets, "get_unique_id_status_map"):
            self._uid_map_last_refresh_ts = now
            return
        try:
            new_map = self.sheets.get_unique_id_status_map() or {}
            added = len(set(new_map.keys()) - self.sheet_seen_ids)
            self.sheet_status_by_id = new_map
            self.sheet_seen_ids = set(new_map.keys())
            self._uid_map_last_refresh_ts = now
            if added:
                print(f"過去採用uidマップ更新: 新規 {added}件 / 合計 {len(self.sheet_seen_ids)}件", flush=True)
        except Exception as e:
            print(f"uidマップ更新失敗(stale 継続): {str(e)[:160]}", flush=True)
            # 失敗しても次の周期まで待つ。リトライ嵐を避ける。
            self._uid_map_last_refresh_ts = now

    def _stop_requested(self) -> bool:
        return Path("data/STOP_REQUESTED").exists()

    def _clear_stop_requested(self):
        try:
            Path("data/STOP_REQUESTED").unlink()
        except FileNotFoundError:
            pass

    async def _watch_target_video(self, page):
        """採用(target=True)した動画は **最後まで** 視聴する。

        TikTok アルゴリズムから見て complete view rate(完視聴率)は最も強い
        好意シグナル。stealth 候補に対して probability で like も発火させて
        いるが、ここで完視聴することで「この uid のような動画を増やせ」と
        TikTok に明確に伝える。

        実装方針:
          1. 動画を再生開始(muted のまま、isTrusted は影響しない)
          2. duration / currentTime を取得して残り再生時間を計算
          3. 残り時間 + 0.5 秒 sleep(余裕分)
          4. duration 不明時は安全側で 30 秒(投稿の typical 上限)を上限に
        """
        await _stop_pause_guard(page)  # 念のため旧 interval を全部 clear
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

        # 残り再生時間を取得
        try:
            info = await page.evaluate("""() => {
              const v = Array.from(document.querySelectorAll('video')).find(v => {
                const r = v.getBoundingClientRect();
                return r.width > 120 && r.height > 180;
              });
              if (!v) return null;
              return {
                duration: Number(v.duration || 0),
                currentTime: Number(v.currentTime || 0)
              };
            }""")
        except Exception:
            info = None

        WATCH_FLOOR = 8.0   # 最低 8 秒は見る(極端に短い動画でも好意シグナルを送る)
        WATCH_CEIL = 60.0   # 上限 60 秒(長尺動画の暴走防止)

        if info and isinstance(info, dict):
            duration = float(info.get("duration") or 0)
            current = float(info.get("currentTime") or 0)
            if 0 < duration <= WATCH_CEIL:
                remain = max(WATCH_FLOOR, duration - current + 0.5)
                wait_sec = min(WATCH_CEIL, remain)
            else:
                # duration 不明 or 長尺すぎ → 安全側で 30 秒視聴
                wait_sec = 30.0
        else:
            wait_sec = 30.0

        print(f"target視聴: {wait_sec:.1f}秒(完視聴シグナル)", flush=True)
        await asyncio.sleep(wait_sec)

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
            self._uid_map_last_refresh_ts = time.time()
            print(f"過去記載済みIDを読み込みました: {len(self.sheet_seen_ids)}件", flush=True)
        except Exception as e:
            print(f"過去記載済みIDの読み込みに失敗: {e}", flush=True)
            self.sheet_seen_ids = set()
            self.sheet_status_by_id = {}

        async with async_playwright() as p:
            # stealth 版: launch_persistent_context ではなく、1_launch_chrome.command で
            # 立ち上げてある実Chromeに CDP 接続する。検知耐性は probe.py で 60/60 完走済み。
            cdp_url = getattr(self.cfg.browser_stealth, "cdp_url", "http://localhost:9222")
            print(f"既存Chrome(CDP {cdp_url})に接続します...", flush=True)
            print("先に 1_launch_chrome.command を起動して、TikTokおすすめフィードを開いておいてください。", flush=True)
            try:
                browser = await p.chromium.connect_over_cdp(cdp_url)
            except Exception as e:
                print(f"CDP接続失敗: {str(e)[:200]}", flush=True)
                print("1_launch_chrome.command が起動していません。", flush=True)
                self.notifier.send("CDP接続失敗で停止")
                return
            context = browser.contexts[0] if browser.contexts else await browser.new_context()
            # Page Visibility 偽装などを以降の全ページに注入
            try:
                await context.add_init_script(STEALTH_INIT_JS)
            except Exception:
                pass

            page = None
            for pg in context.pages:
                if "tiktok.com" in (pg.url or ""):
                    page = pg
                    break
            if page is None:
                page = context.pages[0] if context.pages else await context.new_page()
            # 既存タブには init script が後乗りなので手動で 1 回注入
            try:
                await page.evaluate(STEALTH_INIT_JS)
            except Exception:
                pass

            try:
                self.scraper.attach_follower_response_cache(page)
            except Exception:
                pass

            if "tiktok.com" not in (page.url or ""):
                try:
                    await page.goto(self.cfg.browser.start_url, wait_until="domcontentloaded", timeout=20000)
                except Exception as e:
                    print(f"TikTok遷移エラー(続行): {str(e)[:180]}", flush=True)

            print(f"CDP接続OK / page={page.url}", flush=True)
            await asyncio.sleep(self.cfg.browser.startup_wait_sec)

            while True:
                if (time.time() - start_ts) > self.cfg.browser.max_runtime_minutes * 60:
                    self.notifier.send("最大稼働時間に到達したため停止")
                    break

                self._maybe_refresh_uid_map()

                already_advanced = False
                try:
                    already_advanced = bool(await asyncio.wait_for(self._process_one(page), timeout=90))
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

                # _process_one が内部で _force_advance_after_skip を呼んでいた場合は
                # ここで二重に next_post すると 2 動画進んでしまう(連続2スワイプ)。
                # 内部スワイプ済みは True を返す約束なので、True のときは skip する。
                if not already_advanced:
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
        """スキップ系で同じ動画に張り付かないよう次へ進める。
        stealth: 1 番目に scraper.next_post(= human_swipe wheel + chevron + ArrowDown)
        を試し、失敗時のみ各種キー/scroll にフォールバック。
        wait は 500ms — 短すぎると次の _process_one が前動画の uid を拾って
        二重スキップ(2 動画進む)が起きる。"""
        for method in range(1, 7):
            try:
                if method == 1:
                    await self.scraper.next_post(page)
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
                await page.wait_for_timeout(500)
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
            # follow=following なら完視聴シグナルを送らない。フォロー中アカウントを
            # 完視聴すると、TikTok はフォロー中の似た系統ばかり次に出すようになり、
            # 「新規候補が見つからずフォロー中アカウントしか出ない」状態に陥る。
            # フォロー外で過去採用済みのときだけ完視聴して positive signal を送る。
            try:
                follow_state = await self.scraper.detect_follow_state_local(page)
            except Exception:
                follow_state = "unknown"
            try:
                self.db.touch_seen(uid)
            except Exception:
                pass
            if follow_state == "following":
                print(f"[PAST_RECOMMENDED_FOLLOWING_SKIP] account_id={uid}", flush=True)
                await self._force_advance_after_skip(page, uid)
                return True

            # 過去採用済みアカウントの動画は **完視聴** してからスワイプ。
            # 即スワイプすると TikTok アルゴから「以前好きだった系統を今は拒否」と
            # 読まれ、似た傾向の新規候補が枯渇する。既処理が増えるほどこの侵食が
            # 効いて、新規 recommended がどんどん減る悪循環になる。
            # 完視聴(complete view)は TikTok の最強好意シグナル。
            print(f"[WATCH_RECOMMENDED_ALREADY_PROCESSED] account_id={uid}", flush=True)
            await self._watch_target_video(page)
            await self._force_advance_after_skip(page, uid)
            return True
        if self._is_excluded_status(status):
            prev_reason = str((processed or {}).get("reason") or "")
            try:
                self.db.touch_seen(uid)
            except Exception:
                pass

            # follow=following なら再判定も視聴もしない(救済して完視聴したら
            # フォロー中アカウントだらけになりフィードが偏る)。dedup セット
            # の前にチェックすることで、ユーザーがセッション中に対象アカウントを
            # アンフォローした場合は次の遭遇で正常に再判定パスに入れる。
            try:
                follow_state = await self.scraper.detect_follow_state_local(page)
            except Exception:
                follow_state = "unknown"
            if follow_state == "following":
                print(f"[PAST_EXCLUDED_FOLLOWING_SKIP] account_id={uid} status={status} reason={prev_reason}", flush=True)
                await self._force_advance_after_skip(page, uid)
                return True

            # 過去に除外したが、今出ている動画は別かもしれず、過去判定が誤りだった
            # 可能性もある。スワイプを先にやってから AI を裏で叩いて、target=True
            # なら recommended に昇格する。重要なのは「視聴時間は最短化」。
            # 同セッション内で同 uid を 2 度再判定しない(AI コスト & 過剰視聴防止)。
            if uid in self._past_excluded_rechecked:
                print(f"[PAST_EXCLUDED_SKIP] account_id={uid} status={status} reason={prev_reason}", flush=True)
                await self._force_advance_after_skip(page, uid)
                return True

            self._past_excluded_rechecked.add(uid)

            # フォロワー数 / プロフィール紹介文 を並列で取得(視聴時間短縮)。
            # 通常フロー(L877〜)と同じ取得関数を使うので、recovered 行も
            # フォロワー / bio 入りで Sheets に書ける。
            try:
                fc_result, pt_result = await asyncio.gather(
                    self.scraper.detect_follower_count_from_feed(page, uid),
                    self.scraper.detect_profile_text_from_feed(page, uid),
                    return_exceptions=True,
                )
            except Exception:
                fc_result, pt_result = None, None

            follower_count = None
            follower_source = ""
            if isinstance(fc_result, tuple):
                if isinstance(fc_result[0], int):
                    follower_count = fc_result[0]
                follower_source = fc_result[1] if len(fc_result) > 1 and fc_result[1] else ""
            profile_text = ""
            profile_source = ""
            if isinstance(pt_result, tuple):
                profile_text = pt_result[0] or ""
                profile_source = pt_result[1] if len(pt_result) > 1 and pt_result[1] else ""

            # キャッシュで取れなかった分は hover ポップオーバーで補完。
            # 取得済みの分は上書きしない。
            if follower_count is None or not profile_text:
                try:
                    hover_data = await self.scraper.enrich_via_hover(page, uid)
                except Exception as e:
                    print(f"[PAST_EXCLUDED_RECHECK_HOVER_ERROR] account_id={uid} err={str(e)[:120]}", flush=True)
                    hover_data = {"follower_count": None, "bio": ""}
                if follower_count is None and hover_data.get("follower_count") is not None:
                    follower_count = int(hover_data["follower_count"])
                    follower_source = "hover-popover"
                if not profile_text and hover_data.get("bio"):
                    profile_text = hover_data["bio"]
                    profile_source = "hover-popover"

            try:
                object.__setattr__(candidate, "follower_count", follower_count if follower_count is not None else "")
                object.__setattr__(candidate, "follower_source", follower_source or "")
                if profile_text:
                    object.__setattr__(candidate, "signature", profile_text)
                    object.__setattr__(candidate, "bio", profile_text)
                    object.__setattr__(candidate, "profile_text_source", profile_source or "")
            except Exception:
                pass

            # フォロワー閾値ガード: 大手は再判定対象外。AI も呼ばずスワイプして抜ける。
            max_followers_threshold = int(getattr(self.cfg.rules, "max_followers", 2000) or 2000)
            if follower_count is not None and follower_count >= max_followers_threshold:
                print(f"[PAST_EXCLUDED_RECHECK_SKIP_BIG_FOLLOWER] account_id={uid} fc={follower_count}", flush=True)
                await self._force_advance_after_skip(page, uid)
                return True

            # プロフィール / ハッシュタグを最新状態に揃えてから現行 ローカルルール で再評価。
            # 過去の除外理由が今でも有効か(NG ワード追加など)を反映する。
            try:
                candidate = await _repair_candidate_profile_and_hashtags(page, candidate, getattr(self, "scraper", None))
            except Exception as e:
                print(f"[PAST_EXCLUDED_RECHECK_REPAIR_ERROR] account_id={uid} err={str(e)[:120]}", flush=True)
            local_reason = local_skip_reason(candidate, self.cfg.rules)
            if local_reason and not local_reason.startswith(_AI_OVERRIDE_LOCAL_REASON_PREFIXES):
                # 確証性が高い NG(未成年 / 外部リンク / 類似除外 等)は AI に振らずに skip。
                print(f"[PAST_EXCLUDED_RECHECK_SKIP_LOCAL] account_id={uid} reason={local_reason}", flush=True)
                await self._force_advance_after_skip(page, uid)
                return True
            if local_reason:
                # heuristic 系("ランダムID/..." "外国語/海外(...)" 等)は uid + テキストだけの
                # 推定なので誤検出が多い。AI に画像で本人らしさを確認させる。
                print(f"[PAST_EXCLUDED_RECHECK_LOCAL_AI_OVERRIDE] account_id={uid} reason={local_reason} → asking AI", flush=True)

            # ここまで来てやっと AI 再判定対象。スクショは swipe 前のみ可能。
            print(f"[PAST_EXCLUDED_RECHECK] account_id={uid} prev_status={status} reason={prev_reason} fc={follower_count}", flush=True)
            screenshot_path = None
            try:
                screenshot_path = await self.scraper.screenshot_current(page, uid)
            except Exception as e:
                print(f"[PAST_EXCLUDED_RECHECK_NO_SCREENSHOT] account_id={uid} err={str(e)[:120]}", flush=True)

            if not screenshot_path:
                await self._force_advance_after_skip(page, uid)
                return True

            # AI を同期実行。target=True なら完視聴(positive signal)、target=False なら即 swipe。
            # 背景化しない理由: 救済確定時に動画がまだ画面上にある状態で _watch_target_video を呼ぶ
            # 必要があるため。背景タスクで判定する場合は既にスワイプ済みで完視聴できない。
            try:
                result = await asyncio.to_thread(
                    self.ai.judge_with_fallback_if_needed, screenshot_path, candidate.dict()
                )
                if isinstance(result, dict) and "cute_score" in result:
                    result["cute_score"] = _clamp_ai_score_0_10(result.get("cute_score", ""))
            except Exception as e:
                print(f"[PAST_EXCLUDED_RECHECK_ERROR] account_id={uid} err={str(e)[:120]}", flush=True)
                await self._force_advance_after_skip(page, uid)
                return True

            if not result.get("target"):
                print(f"[PAST_EXCLUDED_RECHECK_REJECT] account_id={uid} (still excluded)", flush=True)
                await self._force_advance_after_skip(page, uid)
                return True

            # 救済確定: DB/Sheets 更新 → 完視聴 → swipe(target=True 通常フローと同等)
            score = str(result.get("cute_score", ""))
            reason = str(result.get("reason", ""))
            model_used = str(result.get("model_used", ""))
            print(f"[PAST_EXCLUDED_RECOVERED] account_id={uid} score={score} reason={reason}", flush=True)

            try:
                self.db.mark(uid, "recommended", reason, candidate.profile_url, candidate.post_url, screenshot_path)
            except Exception as e:
                print(f"[PAST_EXCLUDED_RECOVERED_DB_FAIL] account_id={uid} err={str(e)[:120]}", flush=True)

            try:
                self.sheets.append(
                    "recommended",
                    candidate.to_row(self.cfg.collector_name, reason=reason, score=score, model_used=model_used),
                )
                self.written_count += 1
            except Exception as e:
                print(f"[PAST_EXCLUDED_RECOVERED_SHEET_FAIL] account_id={uid} err={str(e)[:120]}", flush=True)

            await self._watch_target_video(page)
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

    async def _process_one(self, page) -> bool:
        """1 動画を処理する。戻り値 True なら **このメソッド内ですでに次の動画へ
        スワイプ済み** であることを呼び出し側に伝え、main loop の追加 next_post
        を抑止する(連続2スワイプ防止)。False なら main loop が next_post する。"""
        candidate = await self.scraper.current_candidate(page)

        # === stealth: 二重スキップ防止ガード ===
        # _force_advance_after_skip の直後で DOM がまだ前動画のままだと、
        # current_candidate が前動画の uid を返す → 既処理判定 → もう一度
        # _force_advance_after_skip(2 動画進む)が起きる。前回 uid と同じ
        # かつ既処理ならスキップ前に追加待機して再取得する。
        if (
            candidate
            and getattr(candidate, "unique_id", "")
            and self._last_seen_uid
            and candidate.unique_id == self._last_seen_uid
        ):
            await asyncio.sleep(0.5)
            recheck = await self.scraper.current_candidate(page)
            if recheck and getattr(recheck, "unique_id", "") and recheck.unique_id != self._last_seen_uid:
                candidate = recheck  # 新しい動画の uid が取れた → 採用
            # 取れなければそのまま進める(reload guard が後段で動く)

        if not candidate:
            self.db.event("warn", "candidate取得失敗")
            return False

        # === stealth: 同じ uid に連続で当たったら Chrome を reload して復帰 ===
        # Wi-Fi 不調や TikTok 側の一時的な固まりで先に進まないケースを自動回復する。
        if candidate.unique_id and candidate.unique_id == self._last_seen_uid:
            self._same_uid_streak += 1
        else:
            self._same_uid_streak = 0
        self._last_seen_uid = candidate.unique_id or ""

        algo_st = getattr(self.cfg, "algorithm_stealth", None)
        stuck_threshold = int(getattr(algo_st, "stuck_reload_threshold", 3) or 3)
        max_reloads = int(getattr(algo_st, "stuck_max_reloads", 6) or 6)
        if self._same_uid_streak >= stuck_threshold:
            self._reload_count += 1
            if self._reload_count > max_reloads:
                msg = f"フィード詰まりが{max_reloads}回続いたため停止 (最終 uid={candidate.unique_id})"
                print(msg, flush=True)
                self.notifier.send(msg)
                Path("data/STOP_REQUESTED").touch()
                return True
            print(
                f"フィード詰まり検出: uid={candidate.unique_id} streak={self._same_uid_streak}"
                f" → page.reload() #{self._reload_count}",
                flush=True,
            )
            self.db.event("info", f"page.reload (stuck on {candidate.unique_id})")
            try:
                await page.reload(wait_until="domcontentloaded", timeout=30000)
            except Exception as e:
                print(f"page.reload エラー: {str(e)[:160]}", flush=True)
            await asyncio.sleep(self.cfg.browser.startup_wait_sec)
            self._same_uid_streak = 0
            self._last_seen_uid = ""
            # reload で DOM が完全に切り替わったので追加スワイプは不要
            return True

        processed = self.db.get(candidate.unique_id)
        if processed:
            if await self._handle_already_processed_candidate(page, candidate, processed):
                return True

        if candidate.unique_id in self.sheet_seen_ids:
            if await self._handle_already_processed_candidate(page, candidate, None):
                return True
            print(f"既処理スキップ: {candidate.unique_id}", flush=True)
            await self._force_advance_after_skip(page, candidate.unique_id)
            return True

        follow_state = await self.scraper.detect_follow_state_local(page)
        if follow_state == "following":
            reason = "フォロー中"
            print(f"ローカル除外: {candidate.unique_id} / {reason}", flush=True)
            self.db.mark(candidate.unique_id, "skipped", reason, candidate.profile_url, candidate.post_url, "")
            self.sheet_seen_ids.add(candidate.unique_id)
            row = candidate.to_row(self.cfg.collector_name, reason=reason, model_used="local:check-path")
            # 判定 → 即スワイプ → 後で Sheets 書き込み。Sheets API は数百ms〜1s かかる
            # ため、先にやると「興味あり」と誤認されかねない長さ視聴することになる。
            # 既処理スキップと同じ速度感を出すのが狙い。
            await self._negative_feedback_for_current_exclusion(page, candidate, "skipped", reason)
            await self._force_advance_after_skip(page, candidate.unique_id)
            self.sheets.append("skipped", row)
            return True

        if follow_state != "not_following":
            reason = "フォロー状態不明"
            print(f"ローカル除外: {candidate.unique_id} / {reason}", flush=True)
            self.db.mark(candidate.unique_id, "skipped", reason, candidate.profile_url, candidate.post_url, "")
            self.sheet_seen_ids.add(candidate.unique_id)
            row = candidate.to_row(self.cfg.collector_name, reason=reason, model_used="local:follow-unknown")
            await self._negative_feedback_for_current_exclusion(page, candidate, "skipped", reason)
            await self._force_advance_after_skip(page, candidate.unique_id)
            self.sheets.append("skipped", row)
            return True


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


        # キャッシュで follower / profile_text が取れなかったときは @uid を hover して
        # ポップオーバーから補完する。Sheets の「おすすめ」記入時にこれらの列が空欄に
        # なる現象を防ぐ。取得済みの値は上書きしない。
        if follower_count is None or not profile_text:
            try:
                hover_data = await self.scraper.enrich_via_hover(page, candidate.unique_id)
            except Exception as e:
                print(f"hover補完エラー: {candidate.unique_id} / {str(e)[:120]}", flush=True)
                hover_data = {"follower_count": None, "bio": ""}
            if follower_count is None and hover_data.get("follower_count") is not None:
                follower_count = int(hover_data["follower_count"])
                follower_source = "hover-popover"
                try:
                    object.__setattr__(candidate, "follower_count", follower_count)
                    object.__setattr__(candidate, "follower_source", follower_source)
                except Exception:
                    pass
            if not profile_text and hover_data.get("bio"):
                profile_text = hover_data["bio"]
                profile_source = "hover-popover"


        if profile_text:


            try:


                object.__setattr__(candidate, "signature", profile_text)


                object.__setattr__(candidate, "bio", profile_text)


                object.__setattr__(candidate, "profile_text_source", profile_source or "")


            except Exception:


                pass



        # === stealth: 候補性判定 + like 発火 ===
        # 早期 skip するのは「明らかに対象外」だけに絞る:
        #   - 過去採用済み:再記入を防ぐ
        #   - フォロワー数が判明していて閾値以上:大手は対象外
        # フォロワー不明(盗聴キャッシュにまだ載っていない)は AI に流す。
        # 取りこぼし防止 > AI コスト節約。
        algo_st = getattr(self.cfg, "algorithm_stealth", None)
        if algo_st and getattr(algo_st, "enable_candidacy_check", True):
            fc = follower_count if isinstance(follower_count, int) else None
            is_past_adopted = self.sheet_status_by_id.get(candidate.unique_id) == "recommended"
            max_followers_threshold = int(getattr(self.cfg.rules, "max_followers", 2000) or 2000)
            if is_past_adopted:
                # 他PCで採用された uid。完視聴して positive signal を送る。
                # db.mark はしない(sheet 側の recommended 状態を local "skipped" で
                # 上書きしないため)。sheet_seen_ids には入れて Sheets 重複追記を防ぐ。
                print(f"stealth past_adopted: {candidate.unique_id} (watch for signal)", flush=True)
                self.sheet_seen_ids.add(candidate.unique_id)
                await self._watch_target_video(page)
                await self._force_advance_after_skip(page, candidate.unique_id)
                return True
            if fc is not None and fc >= max_followers_threshold:
                reason = f"stealth_candidacy:follower>={max_followers_threshold}"
                print(f"stealth候補外: {candidate.unique_id} / {reason}", flush=True)
                self.db.mark(candidate.unique_id, "skipped", reason, candidate.profile_url, candidate.post_url, "")
                self.sheet_seen_ids.add(candidate.unique_id)
                await self._force_advance_after_skip(page, candidate.unique_id)
                return True

            # like はフォロワー数が判明していて閾値未満のときだけ発火。
            # 不明だと「人気アカウント」の可能性もあるので like の安全網を切らない。
            is_like_target = fc is not None and fc < max_followers_threshold
            if is_like_target and getattr(algo_st, "enable_like", True):
                like_prob = float(getattr(algo_st, "like_probability", 0.20))
                like_interval = float(getattr(algo_st, "like_min_interval_sec", 90))
                now_mono = time.monotonic()
                if (
                    candidate.unique_id not in self._liked_uids
                    and random.random() < like_prob
                    and (now_mono - self._last_like_ts) >= like_interval
                ):
                    try:
                        like_result = await _stealth_fire_like(page)
                        print(f"stealth like: {candidate.unique_id} / {like_result}", flush=True)
                        if like_result.get("ok"):
                            self._last_like_ts = now_mono
                            self._liked_uids.add(candidate.unique_id)
                    except Exception as e:
                        print(f"stealth like error: {str(e)[:120]}", flush=True)

        # minimal pause before judgement: 判定前に動画を停止し、対象外視聴を増やさない



        await _start_pause_guard(page)



        # profile/hashtag repair before local rules
        try:
            candidate = await _repair_candidate_profile_and_hashtags(page, candidate, getattr(self, "scraper", None))
        except Exception as e:
            print(f"profile/hashtag repair error: {str(e)[:120]}", flush=True)
        reason = local_skip_reason(candidate, self.cfg.rules)
        if reason and not reason.startswith(_AI_OVERRIDE_LOCAL_REASON_PREFIXES):
            # 確証性が高い NG(未成年 / 外部リンク / 類似除外 等)は AI に振らずに skip。
            print(f"ローカル除外: {candidate.unique_id} / {reason}", flush=True)
            self.db.mark(candidate.unique_id, "skipped", reason, candidate.profile_url, candidate.post_url, "")
            self.sheet_seen_ids.add(candidate.unique_id)
            row = candidate.to_row(self.cfg.collector_name, reason=reason, model_used="local:no-screenshot")
            await self._negative_feedback_for_current_exclusion(page, candidate, "skipped", reason)
            await self._force_advance_after_skip(page, candidate.unique_id)
            self.sheets.append("skipped", row)
            return True
        if reason:
            # heuristic 系("ランダムID/..." "外国語/海外(...)" 等)は uid + テキストだけの
            # 推定で誤検出が多い。AI に画像で本人らしさを確認させる。
            print(f"ローカル heuristic hit, AI に判定移譲: {candidate.unique_id} / {reason}", flush=True)

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
            return False

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
            return False

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
        # target=True 採用後 or AI除外後はこの関数内ではスワイプしない → main loop が next_post する
        return False

