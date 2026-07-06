from __future__ import annotations

import asyncio
import json
import random
import time
from datetime import datetime
from pathlib import Path
from collections import deque
from playwright.async_api import async_playwright
from .scraper import TikTokScraper
from .rules import local_skip_reason, detect_blackband
from ._rules_parts import user_digits_id as _user_digits_id
from ._stealth import STEALTH_INIT_JS, fire_like as _stealth_fire_like


# ローカルルールで弾かれた reason のうち、AI 画像判定にバトンタッチするべき
# heuristic 系の prefix。uid + テキストだけの判定は誤検出が多いので、AI に画像で
# 本人らしさを確認させる方が正確。確証性が高い NG(未成年系 / 外部リンク /
# 類似除外 / フォロワー数 等)は引き続き早期スキップする。
# 新規候補にも 過去除外 uid の再判定にも同じ集合を適用する。
#
# 「外国語/海外(...)」は早期 skip 復帰済(コミット d27fb74)。
# uid heuristic(「ランダムID/海外・量産寄り」)は `amanecco721` のような
# 日本人の数字サフィックス命名で誤発火するため AI 確認を継続する。
# ただし「ランダムID/完全英字(海外)」(連続子音 3+ = ローマ字日本語あり得ない)
# は確定海外なので AI override から外す。これは prefix が「ランダムID/完全英字」
# でしか始まらないため、ここでは「ランダムID/海外」の方を明示する。
_AI_OVERRIDE_LOCAL_REASON_PREFIXES: tuple[str, ...] = (
    "ランダムID/海外・量産寄り",
    "ランダムID/プロフィール紹介文空欄",
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
    """AI 判定中に動画が視聴シグナルを累積しないよう、超スロー再生(0.001x)で停止状態に近づける。

    pause() は TikTok の anti-bot 検知に引っかかりやすく画面フリッカーも出るため、
    playbackRate=0.001 で代替する。視覚上はほぼ静止画と同じで違和感がない。
    _stop_pause_guard / _watch_target_video が playbackRate=1.0 に戻す。"""
    try:
        await page.evaluate("""
        () => {
          if (window.__tiktokPauseGuardMinimal) return;
          window.__tiktokPauseGuardMinimal = setInterval(() => {
            try {
              const vw = innerWidth, vh = innerHeight;
              const v = Array.from(document.querySelectorAll('video'))
                .map(v => { const r = v.getBoundingClientRect();
                  return {v, area: Math.max(0, Math.min(r.right, vw) - Math.max(r.left, 0))
                                  * Math.max(0, Math.min(r.bottom, vh) - Math.max(r.top, 0))}; })
                .filter(x => x.area > 5000).sort((a,b) => b.area - a.area)[0]?.v;
              if (v && v.playbackRate > 0.002) v.playbackRate = 0.001;
            } catch(e) {}
          }, 300);
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
          try {
            const vw = innerWidth, vh = innerHeight;
            const v = Array.from(document.querySelectorAll('video'))
              .map(v => { const r = v.getBoundingClientRect();
                return {v, area: Math.max(0, Math.min(r.right, vw) - Math.max(r.left, 0))
                                * Math.max(0, Math.min(r.bottom, vh) - Math.max(r.top, 0))}; })
              .filter(x => x.area > 5000).sort((a,b) => b.area - a.area)[0]?.v;
            if (v) v.playbackRate = 1.0;
          } catch(e) {}
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
        # フィード詰まり検出(同じ uid N 連続) → data/RESTART_CHROME を touch して
        # main.py に exit code 77 を返させる。Chrome 全再起動 + ループ再開は
        # 4_overnight_run.command(ラッパー)が担当する。
        self._last_seen_uid = ""
        self._same_uid_streak = 0
        # フィード詰まり(同じ uid N 連続)時のリカバリ試行回数。
        # 即 Chrome 再起動ではなく、まず手動相当の操作(前へ戻る→戻る→大きくスワイプ)を
        # uid ごとに最大 3 回試す。3 回とも失敗したら Chrome 再起動を要求する。
        self._stuck_recovery_attempts: dict[str, int] = {}
        self._last_openai_quota_notify_ts: float = 0.0

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

    def _notify_openai_quota_exceeded(self, err: Exception) -> None:
        err_str = str(err)
        if "429" not in err_str and "quota" not in err_str.lower():
            return
        now = time.time()
        if now - self._last_openai_quota_notify_ts < 3600:
            return
        self._last_openai_quota_notify_ts = now
        msg = "⚠️ OpenAI APIクォータ超過 — AI判定が停止しています。請求ページで残高を確認してください。"
        print(msg, flush=True)
        try:
            self.notifier.send(msg)
        except Exception:
            pass

    def _stop_requested(self) -> bool:
        return Path("data/STOP_REQUESTED").exists()

    def _clear_stop_requested(self):
        try:
            Path("data/STOP_REQUESTED").unlink()
        except FileNotFoundError:
            pass

    def _restart_chrome_requested(self) -> bool:
        return Path("data/RESTART_CHROME").exists()

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

        # 視聴時間レンジは短めに振っておく。1 セッションあたりの動画閲覧数が増え、
        # 既処理プールが大きい状況下でも新規候補と遭遇する確率を上げる。
        # 完視聴シグナルは「最後まで再生」で送るのが理想だが、現実には floor=6 秒で
        # も positive signal は十分通る(アルゴが他指標と合算で判断するため)。
        WATCH_FLOOR = 6.0   # 最低 6 秒は見る
        WATCH_CEIL = 12.0   # 上限 12 秒(長尺動画は途中で抜ける)

        if info and isinstance(info, dict):
            duration = float(info.get("duration") or 0)
            current = float(info.get("currentTime") or 0)
            if 0 < duration <= WATCH_CEIL:
                remain = max(WATCH_FLOOR, duration - current + 0.5)
                wait_sec = min(WATCH_CEIL, remain)
            else:
                # duration 不明 or 長尺すぎ → 短めに 10 秒で抜ける
                wait_sec = 10.0
        else:
            wait_sec = 10.0

        print(f"target視聴: {wait_sec:.1f}秒(完視聴シグナル)", flush=True)
        await asyncio.sleep(wait_sec)

    async def _watch_neutral_video(self, page):
        """除外済み・フォロワー範囲外アカウントへの中立シグナル視聴。
        即スワイプすると TikTok アルゴが「この系統嫌い」と読むため、
        2〜3.5 秒だけ見てから抜ける。採用(完視聴)より弱い通過シグナル。"""
        await _stop_pause_guard(page)  # 超スロー中なら通常速度に戻してから中立視聴
        wait_sec = random.uniform(2.0, 3.5)
        print(f"中立視聴: {wait_sec:.1f}秒", flush=True)
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
                # max_runtime_minutes <= 0 のときは無制限。寝てる間ループ運用の既定。
                max_runtime_sec = self.cfg.browser.max_runtime_minutes * 60
                if max_runtime_sec > 0 and (time.time() - start_ts) > max_runtime_sec:
                    print(
                        f"最大稼働時間 {self.cfg.browser.max_runtime_minutes} 分に到達したため停止します。",
                        flush=True,
                    )
                    self.notifier.send("最大稼働時間に到達したため停止")
                    break

                self._maybe_refresh_uid_map()

                already_advanced = False
                _timed_out = False
                try:
                    already_advanced = bool(await asyncio.wait_for(self._process_one(page), timeout=90))
                except asyncio.TimeoutError:
                    print("1投稿の処理が90秒を超えたため次へ進みます。", flush=True)
                    _timed_out = True
                except Exception as e:
                    print(f"処理エラー: {str(e)[:160]}", flush=True)

                self.processed_count += 1

                if self._stop_requested():
                    print("安全停止要求を検知しました。停止します。", flush=True)
                    self.notifier.send("TikTok Collector 安全停止")
                    self._clear_stop_requested()
                    break

                if self._restart_chrome_requested():
                    # ファイルは main.py 側で消費・削除し exit code 77 を返す。
                    # ここでは while ループを抜けるだけ。
                    print("Chrome 全再起動要求を検知しました。終了します。", flush=True)
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
                    # タイムアウト後は CDP が未完のままでブラウザがブロックしている
                    # 可能性があるため、next_post 自体にも短めのタイムアウトを設ける。
                    # 失敗したらページ再ナビゲートで回復を試み、それも無理なら再起動。
                    _next_timeout = 20 if _timed_out else None
                    try:
                        if _next_timeout:
                            await asyncio.wait_for(self.scraper.next_post(page), timeout=_next_timeout)
                        else:
                            await self.scraper.next_post(page)
                    except Exception as e:
                        print(f"next_post 失敗: {str(e)[:120]}", flush=True)
                        try:
                            print("ページ再ナビゲートでリカバリ試行中...", flush=True)
                            await asyncio.wait_for(
                                page.goto(self.cfg.browser.start_url, wait_until="domcontentloaded"),
                                timeout=20,
                            )
                            print("ページ再ナビゲート完了。", flush=True)
                        except Exception as nav_e:
                            print(f"再ナビゲートも失敗: {str(nav_e)[:120]} → Chrome再起動を要求", flush=True)
                            try:
                                Path("data/RESTART_CHROME").touch()
                            except Exception:
                                pass
                            break
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

    async def _attempt_stuck_recovery(self, page, stuck_uid: str, attempt_no: int = 1) -> bool:
        """フィード詰まり時、手動で抜け出すときの手順を再現する 1 回分の操作。
        attempt_no で段階的にアグレッシブに:
          1: ArrowUp 1 回 → ArrowDown 1 回 → スワイプ(従来動作)
          2: ArrowUp 2 回(2つ前まで戻る) → スワイプ 3 回
          3+: ページリロード(最終手段)
        各段階の最後で uid を再取得し、変わっていれば成功・同じなら失敗。
        """
        try:
            if attempt_no >= 3:
                # 最終手段: ページリロード
                print(f"[STUCK_RECOVERY] attempt={attempt_no} uid={stuck_uid} → page.reload()", flush=True)
                try:
                    await page.reload(wait_until="domcontentloaded")
                except Exception as e:
                    print(f"[STUCK_RECOVERY] reload 失敗: {str(e)[:120]}", flush=True)
                await page.wait_for_timeout(3000)
            elif attempt_no >= 2:
                # 2 段階目: 2 つ前まで戻る → 強めに 3 回スワイプ
                print(f"[STUCK_RECOVERY] attempt={attempt_no} uid={stuck_uid} → ArrowUp×2 + swipe×3", flush=True)
                await page.keyboard.press("ArrowUp")
                await page.wait_for_timeout(1500)
                await page.keyboard.press("ArrowUp")
                await page.wait_for_timeout(1500)
                for _ in range(3):
                    try:
                        await page.mouse.wheel(0, 1800)
                        await page.wait_for_timeout(500)
                    except Exception:
                        pass
                    try:
                        await page.keyboard.press("ArrowDown")
                        await page.wait_for_timeout(500)
                    except Exception:
                        pass
                await page.wait_for_timeout(1500)
            else:
                # 1 段階目(従来動作): 1 つ前 → 戻る → 大きくスワイプ
                await page.keyboard.press("ArrowUp")
                await page.wait_for_timeout(1500)
                await page.keyboard.press("ArrowDown")
                await page.wait_for_timeout(1500)
                for _ in range(3):
                    try:
                        await page.mouse.wheel(0, 1500)
                        await page.wait_for_timeout(300)
                    except Exception:
                        pass
                for _ in range(3):
                    try:
                        await page.keyboard.press("ArrowDown")
                        await page.wait_for_timeout(300)
                    except Exception:
                        pass
                await page.wait_for_timeout(1500)
        except Exception as e:
            print(f"[STUCK_RECOVERY_ERROR] uid={stuck_uid} attempt={attempt_no} err={str(e)[:120]}", flush=True)
            return False

        # uid 変化チェック
        try:
            recheck = await self.scraper.current_candidate(page)
        except Exception:
            return False
        new_uid = recheck.unique_id if recheck and getattr(recheck, "unique_id", "") else ""
        return bool(new_uid and new_uid != stuck_uid)

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
        # Sheets 上「recommended」(おすすめ系タブに既出) なら、ローカル DB が古くて
        # まだ skipped のままでも recommended として扱う。
        # 別 PC が採用した uid をこちらの DB が知らない状態で recheck パスに流すと、
        # AI コストを無駄に払って最後に Sheets 重複でスキップになる。
        db_status = str((processed or {}).get("status") or "")
        sheet_status = str(self.sheet_status_by_id.get(uid, "") or "")
        if sheet_status == "recommended" or db_status == "recommended":
            status = "recommended"
        else:
            status = db_status or sheet_status
        if status == "recommended":
            # 過去採用済みでも、現行ルールで「ハード NG」になる uid は完視聴シグナルを送らない。
            # 例: user始まり数字ID(user1164647411 等)はルール追加前に採用されたケースが
            # 残っており、今 positive signal を送ると同系統の user{digits} が大量に流入する。
            hard_ng = _user_digits_id.check(uid)
            if hard_ng:
                print(f"[PAST_RECOMMENDED_HARD_NG_SKIP] account_id={uid} reason={hard_ng}", flush=True)
                try:
                    self.db.touch_seen(uid)
                except Exception:
                    pass
                await self._force_advance_after_skip(page, uid)
                return True

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
            if follow_state != "not_following":
                # 状態不明(例外・要素未検出)は完視聴シグナルを送らず中立視聴。
                # メインパスと同じく "unknown" = 確認できないので positive signal なし。
                print(f"[PAST_RECOMMENDED_FOLLOW_UNKNOWN_NEUTRAL] account_id={uid}", flush=True)
                await self._watch_neutral_video(page)
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
            # 過去除外 → AI再判定なし。2〜3秒の中立視聴でアルゴシグナルを保ちスキップ。
            # 即スワイプすると「この系統嫌い」とアルゴに読まれ類似候補が枯渇する。
            print(f"[PAST_EXCLUDED_NEUTRAL_WATCH] account_id={uid} status={status}", flush=True)
            self.sheet_seen_ids.add(uid)
            try:
                self.db.touch_seen(uid)
            except Exception:
                pass
            await self._watch_neutral_video(page)
            await self._force_advance_after_skip(page, uid)
            return True
        if status:
            # pending 等(AIエラー保留) → _process_one で再判定(hover あり)
            return False
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

        # === stealth: 同じ uid に N 連続で当たったら Chrome を全再起動 ===
        # ラッパー(4_overnight_run.command)が data/RESTART_CHROME を見て
        # Chrome を kill → 1_launch_chrome.command で起動 → main.py 再開する。
        # 上限なし。ユーザーが Ctrl+C しない限り無限ループ。
        if candidate.unique_id and candidate.unique_id == self._last_seen_uid:
            self._same_uid_streak += 1
        else:
            self._same_uid_streak = 0
        self._last_seen_uid = candidate.unique_id or ""

        algo_st = getattr(self.cfg, "algorithm_stealth", None)
        stuck_threshold = int(getattr(algo_st, "stuck_full_restart_threshold", 10) or 10)
        if self._same_uid_streak >= stuck_threshold:
            # まずはリカバリを試す。手動で stuck から抜け出すときの手順
            # (ArrowUp で 1 つ前 → ArrowDown で戻る → 大きくスワイプ)を最大 N 回。
            # 全部失敗したら Chrome 全再起動を要求する。
            stuck_uid = candidate.unique_id or ""
            max_recovery = int(getattr(algo_st, "stuck_recovery_max_attempts", 3) or 3)
            done = self._stuck_recovery_attempts.get(stuck_uid, 0)
            if done < max_recovery:
                done += 1
                self._stuck_recovery_attempts[stuck_uid] = done
                print(
                    f"フィード詰まり: 同じ uid {stuck_threshold} 連続 → リカバリ試行 "
                    f"{done}/{max_recovery} (uid={stuck_uid})",
                    flush=True,
                )
                ok = await self._attempt_stuck_recovery(page, stuck_uid, attempt_no=done)
                if ok:
                    print(f"フィード詰まり: リカバリ成功 (uid={stuck_uid})", flush=True)
                    # 抜けたので streak をリセット。次回 _process_one では
                    # 新しい uid を見るはず。
                    self._same_uid_streak = 0
                    self._last_seen_uid = ""
                    return True
                # 失敗。次回また同 uid に当たれば streak はさらに伸びるので
                # ここで return True して main loop の追加 swipe を抑止する。
                print(
                    f"フィード詰まり: リカバリ失敗 ({done}/{max_recovery}) (uid={stuck_uid})",
                    flush=True,
                )
                return True
            # 上限到達 → Chrome 全再起動を要求
            print(
                f"フィード詰まり検出: 同じ uid {stuck_threshold} 連続 + リカバリ {max_recovery} 回失敗 "
                f"→ Chrome 全再起動を要求 (uid={stuck_uid})",
                flush=True,
            )
            # ★ touch を最優先で確実にやる。db.event が落ちても restart は走る。
            #   過去に readonly DB で db.event が例外を投げ、後続の touch に到達せず
            #   無限ループになる事象があった。
            try:
                Path("data/RESTART_CHROME").touch()
            except Exception as e:
                print(f"[RESTART_CHROME_TOUCH_FAIL] err={str(e)[:120]}", flush=True)
            try:
                self.db.event(
                    "info",
                    f"restart_chrome (stuck on {stuck_uid} after {max_recovery} recovery attempts)",
                )
            except Exception as e:
                print(f"[RESTART_CHROME_DB_EVENT_FAIL] err={str(e)[:120]}", flush=True)
            return True

        # === 広告チェック(既処理より最優先: 過去除外済み広告も中立視聴なしで即スキップ) ===
        if bool(getattr(candidate, "is_ad", False)):
            signal = str(getattr(candidate, "ad_signal", "") or "unknown")
            reason = f"広告(Sponsored)/{signal}"
            print(f"広告スキップ: {candidate.unique_id} / {reason}", flush=True)
            if candidate.unique_id not in self.sheet_seen_ids:
                self.db.mark(candidate.unique_id, "skipped", reason, candidate.profile_url, candidate.post_url, "")
                self.sheet_seen_ids.add(candidate.unique_id)
                self.sheets.append("skipped", candidate.to_row(self.cfg.collector_name, reason=reason, model_used="local:ad-detected"))
            await self._force_advance_after_skip(page, candidate.unique_id)
            return True

        # === official unique_id チェック(既処理でも高速スキップ) ===
        if "official" in (candidate.unique_id or "").lower():
            reason = "公式/企業系(official_id)"
            print(f"officialスキップ: {candidate.unique_id} / {reason}", flush=True)
            if candidate.unique_id not in self.sheet_seen_ids:
                self.db.mark(candidate.unique_id, "skipped", reason, candidate.profile_url, candidate.post_url, "")
                self.sheet_seen_ids.add(candidate.unique_id)
                self.sheets.append("skipped", candidate.to_row(self.cfg.collector_name, reason=reason, model_used="local:official-id"))
            await self._force_advance_after_skip(page, candidate.unique_id)
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


        # フォロワー数 + プロフィール紹介文を並列取得(直列だと各最大1.5秒 × 2 = 3秒かかる)。
        _fc_res, _pt_res = await asyncio.gather(
            self.scraper.detect_follower_count_from_feed(page, candidate.unique_id),
            self.scraper.detect_profile_text_from_feed(page, candidate.unique_id),
            return_exceptions=True,
        )
        follower_count, follower_source = _fc_res if not isinstance(_fc_res, Exception) else (None, "")
        profile_text, profile_source = _pt_res if not isinstance(_pt_res, Exception) else ("", "")

        try:
            object.__setattr__(candidate, "follower_count", follower_count if follower_count is not None else "")
            object.__setattr__(candidate, "follower_source", follower_source or "")
        except Exception:
            pass

        if profile_text:
            try:
                object.__setattr__(candidate, "signature", profile_text)
                object.__setattr__(candidate, "bio", profile_text)
                object.__setattr__(candidate, "profile_text_source", profile_source or "")
            except Exception:
                pass

        # ローカルルール判定を hover より先に実施。
        # NGワード / 未成年 等のハード除外は hover を呼ばずに即スキップ。
        # hover はローカルルールを通過した新規アカウントのみ実施する。
        await _start_pause_guard(page)

        try:
            candidate = await _repair_candidate_profile_and_hashtags(page, candidate, getattr(self, "scraper", None))
        except Exception as e:
            print(f"profile/hashtag repair error: {str(e)[:120]}", flush=True)

        reason = local_skip_reason(candidate, self.cfg.rules)
        if reason and not reason.startswith(_AI_OVERRIDE_LOCAL_REASON_PREFIXES):
            # 確証性が高い NG(未成年 / 外部リンク / 類似除外 等)は AI に振らずに即スキップ。
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

        # ローカルルール通過後のみ hover 補完を実施(新規アカウントのみ対象)。
        # 過去処理済みアカウントは _handle_already_processed_candidate で先に処理済み。
        hover_data = None
        if follower_count is None or not profile_text:
            try:
                hover_data = await self.scraper.enrich_via_hover(page, candidate.unique_id, hover_wait_sec=1.0)
            except Exception as e:
                print(f"hover補完エラー: {candidate.unique_id} / {str(e)[:120]}", flush=True)
                hover_data = {"follower_count": None, "bio": "", "skip_reason": "hover_exception", "popover_source": None}
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

        # fc 取得経路を JSONL に永続化。
        try:
            acq = {
                "ts": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
                "uid": candidate.unique_id,
                "feed_cache_hit": follower_source == "feed-api-cache" and follower_count is not None,
                "hover_attempted": hover_data is not None,
                "hover_skip_reason": (hover_data or {}).get("skip_reason"),
                "hover_source": (hover_data or {}).get("popover_source"),
                "final_fc": follower_count if isinstance(follower_count, int) else None,
                "final_source": follower_source or None,
                "profile_source": profile_source or None,
                "bio_len": len(profile_text or ""),
            }
            Path("data").mkdir(parents=True, exist_ok=True)
            with Path("data/fc_acquisition.jsonl").open("a", encoding="utf-8") as _f:
                _f.write(json.dumps(acq, ensure_ascii=False) + "\n")
        except Exception:
            pass

        # === stealth: フォロワー数判定(ローカルルールの後に実施)===
        # フォロワー数だけが対象外の場合は中立視聴(2〜3秒)してスキップ。
        # ローカルルールより手前で除外されたアカウントは即スキップ済みのため、
        # ここでの除外はアルゴへの「嫌い」シグナルにならない中立扱いとする。
        algo_st = getattr(self.cfg, "algorithm_stealth", None)
        if algo_st and getattr(algo_st, "enable_candidacy_check", True):
            fc = follower_count if isinstance(follower_count, int) else None
            is_past_adopted = self.sheet_status_by_id.get(candidate.unique_id) == "recommended"
            max_followers_threshold = int(getattr(self.cfg.rules, "max_followers", 2000) or 2000)
            if is_past_adopted:
                print(f"stealth past_adopted: {candidate.unique_id} (watch for signal)", flush=True)
                self.sheet_seen_ids.add(candidate.unique_id)
                await self._watch_target_video(page)
                await self._force_advance_after_skip(page, candidate.unique_id)
                return True
            min_followers_threshold = int(getattr(self.cfg.rules, "min_followers", 0) or 0)
            if fc is None:
                reason = "stealth_candidacy:fc_unknown"
                print(f"stealth候補外: {candidate.unique_id} / {reason}", flush=True)
                self.db.mark(candidate.unique_id, "skipped", reason, candidate.profile_url, candidate.post_url, "")
                self.sheet_seen_ids.add(candidate.unique_id)
                await self._watch_neutral_video(page)
                await self._force_advance_after_skip(page, candidate.unique_id)
                return True
            if fc >= max_followers_threshold:
                reason = f"stealth_candidacy:follower>={max_followers_threshold}"
                print(f"stealth候補外: {candidate.unique_id} / {reason}", flush=True)
                self.db.mark(candidate.unique_id, "skipped", reason, candidate.profile_url, candidate.post_url, "")
                self.sheet_seen_ids.add(candidate.unique_id)
                await self._watch_neutral_video(page)
                await self._force_advance_after_skip(page, candidate.unique_id)
                return True
            if fc < min_followers_threshold:
                reason = f"stealth_candidacy:follower<{min_followers_threshold}"
                print(f"stealth候補外: {candidate.unique_id} / {reason}", flush=True)
                self.db.mark(candidate.unique_id, "skipped", reason, candidate.profile_url, candidate.post_url, "")
                self.sheet_seen_ids.add(candidate.unique_id)
                await self._watch_neutral_video(page)
                await self._force_advance_after_skip(page, candidate.unique_id)
                return True

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
            self._notify_openai_quota_exceeded(e)
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
            self.sheets.append_recommended(
                candidate.to_row(self.cfg.collector_name, reason=reason, score=score, model_used=model_used),
                candidate.follower_count,
            )
            self.sheet_seen_ids.add(candidate.unique_id)
            self.written_count += 1
            # AI採用確定後にのみ like を送信。黒帯・AI除外・保留アカウントには
            # シグナルを送らず、TikTok アルゴを「採用したい系統」に絞って訓練する。
            if algo_st and getattr(algo_st, "enable_like", True):
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

