"""
TikTokCollectorStealth - feed survival probe

目的:
  既存ツールのbot検知を回避できるかを確認する最小ループ。
  - 実Chromeに CDP 接続
  - Page Visibility を常に visible に偽装
  - マウスホイールで人間っぽくスワイプ
  - スワイプ毎に「今表示中の動画ID」「再生中か」を data/probe.jsonl に記録

判定の見方:
  - 同じ動画IDが2回以上連続で出る → フィードが進んでない(検知の疑い)
  - 動画IDが順次変わる → 健康なフィード
"""
from __future__ import annotations

import asyncio
import json
import random
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import yaml
from playwright.async_api import async_playwright, Page


# Sheets だけを引っぱる軽量 cfg。tiktok_collector.config.load_config は
# OPENAI_API_KEY 必須なので、probe では使わずこれだけ渡す。
@dataclass
class _SheetsCfgLite:
    spreadsheet_id: str
    tabs: dict
    auth_mode: str = "oauth"
    oauth_client_json: str = "./credentials/oauth_client.json"
    oauth_token_json: str = "./credentials/token.json"
    service_account_json: str = "./credentials/service_account.json"
    ng_keywords_cache_ttl_sec: int = 600


CDP_URL = "http://localhost:9222"
PROJECT_ROOT = Path(__file__).parent
LOG_PATH = PROJECT_ROOT / "data" / "probe.jsonl"
CONFIG_PATH = PROJECT_ROOT / "config.yaml"
LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

# src/tiktok_collector を import するため
sys.path.insert(0, str(PROJECT_ROOT / "src"))


# ─────────────────────────────────────────────
# stealth init script
# Page Visibility を常に visible に固定し、
# WebDriver痕跡を表面的に消す。
# 実Chromeなので大半は元から問題ないが念のため。
# ─────────────────────────────────────────────
STEALTH_INIT_JS = r"""
(() => {
  try {
    Object.defineProperty(document, 'hidden', { configurable: true, get: () => false });
    Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => 'visible' });
    Object.defineProperty(document, 'webkitHidden', { configurable: true, get: () => false });
    Object.defineProperty(document, 'webkitVisibilityState', { configurable: true, get: () => 'visible' });
    document.addEventListener('visibilitychange', (e) => e.stopImmediatePropagation(), true);
    document.addEventListener('webkitvisibilitychange', (e) => e.stopImmediatePropagation(), true);
  } catch (e) {}

  try {
    if (navigator.webdriver) {
      Object.defineProperty(navigator, 'webdriver', { configurable: true, get: () => undefined });
    }
  } catch (e) {}

  try {
    Object.defineProperty(document, 'hasFocus', { configurable: true, value: () => true });
  } catch (e) {}
})();
"""


def log_event(obj: dict) -> None:
    obj = {"ts": datetime.now().isoformat(timespec="seconds"), **obj}
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")
    print(json.dumps(obj, ensure_ascii=False), flush=True)


# ─────────────────────────────────────────────
# 設定 / 過去採用 uid / フォロワー盗聴
# ─────────────────────────────────────────────
def load_config() -> dict:
    if not CONFIG_PATH.exists():
        return {}
    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_past_adopted_uids(cfg: dict) -> set[str]:
    """Sheets「おすすめ」タブから過去採用 uid を読み込む。失敗時は空集合。
    OPENAI_API_KEY 不要のため、tiktok_collector.config.load_config は通さず
    google_sheets セクションだけを SheetsClient に渡す(verify_ng_setup.py と同方式)。
    """
    gs = (cfg.get("google_sheets") or {})
    if not gs.get("spreadsheet_id") or not gs.get("tabs"):
        log_event({"event": "candidacy_init", "ok": False, "reason": "google_sheets section missing"})
        return set()

    try:
        from tiktok_collector.sheets import SheetsClient  # type: ignore
    except Exception as e:
        log_event({"event": "candidacy_init", "ok": False, "reason": f"import_failed:{e!s:.200}"})
        return set()

    try:
        sheets_cfg = _SheetsCfgLite(
            spreadsheet_id=gs["spreadsheet_id"],
            tabs=gs["tabs"],
            auth_mode=gs.get("auth_mode", "oauth"),
            oauth_client_json=gs.get("oauth_client_json", "./credentials/oauth_client.json"),
            oauth_token_json=gs.get("oauth_token_json", "./credentials/token.json"),
            service_account_json=gs.get("service_account_json", "./credentials/service_account.json"),
            ng_keywords_cache_ttl_sec=int(gs.get("ng_keywords_cache_ttl_sec", 600)),
        )
        client = SheetsClient(sheets_cfg)
        status_map = client.get_unique_id_status_map() or {}
        uids = {uid for uid, status in status_map.items() if status == "recommended"}
        log_event({"event": "candidacy_init", "ok": True, "past_adopted_count": len(uids)})
        return uids
    except Exception as e:
        log_event({"event": "candidacy_init", "ok": False, "reason": f"sheets_failed:{e!s:.200}"})
        return set()


def _attach_follower_response_cache(page: Page) -> None:
    """TikTokフィードAPIレスポンスから authorStats.followerCount を盗聴してキャッシュ。
    プロフィールページは開かないので検知耐性を壊さない。
    scraper.attach_follower_response_cache を probe 用に inline 化。
    """
    if getattr(page, "_follower_cache_attached", False):
        return
    setattr(page, "_follower_cache_attached", True)
    setattr(page, "_follower_count_cache", {})

    def pick_uid(obj):
        if not isinstance(obj, dict):
            return ""
        for k in ("uniqueId", "unique_id", "id", "nickname"):
            v = obj.get(k)
            if isinstance(v, str) and v:
                return v.replace("@", "")
        return ""

    def pick_count(obj):
        if not isinstance(obj, dict):
            return None
        for k in ("followerCount", "follower_count", "followers", "fans", "fansCount"):
            v = obj.get(k)
            try:
                if v is not None and str(v).strip() != "":
                    n = int(float(str(v).replace(",", "")))
                    if 0 <= n < 1_000_000_000:
                        return n
            except Exception:
                pass
        return None

    def walk(obj, cache, depth=0):
        if depth > 12 or obj is None:
            return
        if isinstance(obj, list):
            for x in obj:
                walk(x, cache, depth + 1)
            return
        if not isinstance(obj, dict):
            return
        author = obj.get("author") or obj.get("authorInfo") or obj.get("user") or {}
        stats = obj.get("authorStats") or obj.get("stats") or {}
        if isinstance(author, dict):
            uid = pick_uid(author)
            cnt = (
                pick_count(stats)
                or pick_count(author.get("stats") or {})
                or pick_count(author.get("authorStats") or {})
            )
            if uid and cnt is not None:
                cache[uid] = cnt
        uid2 = pick_uid(obj)
        cnt2 = pick_count(obj.get("authorStats") or {}) or pick_count(obj.get("stats") or {})
        if uid2 and cnt2 is not None:
            cache[uid2] = cnt2
        for v in obj.values():
            if isinstance(v, (dict, list)):
                walk(v, cache, depth + 1)

    async def handle_response(response):
        try:
            url = response.url or ""
            if "tiktok.com" not in url:
                return
            if not any(s in url for s in ("/api/", "item_list", "recommend", "feed")):
                return
            try:
                data = await response.json()
            except Exception:
                return
            cache = getattr(page, "_follower_count_cache", {}) or {}
            walk(data, cache)
            setattr(page, "_follower_count_cache", cache)
        except Exception:
            return

    page.on("response", lambda response: asyncio.create_task(handle_response(response)))


def get_follower_count_from_cache(page: Page, uid: str) -> int | None:
    uid = (uid or "").replace("@", "").strip()
    if not uid:
        return None
    cache = getattr(page, "_follower_count_cache", {}) or {}
    val = cache.get(uid)
    if val is None:
        return None
    try:
        return int(val)
    except Exception:
        return None


# ─────────────────────────────────────────────
# Like 発火(follow はやらない)
# ─────────────────────────────────────────────
async def _find_like_button(page: Page) -> dict | None:
    """画面中央の動画カード内の「いいね」ボタンの座標を取る。"""
    try:
        return await page.evaluate(r"""
        () => {
          const vw = innerWidth, vh = innerHeight;
          const visible = (el) => {
            const r = el.getBoundingClientRect();
            const s = getComputedStyle(el);
            return r.width > 16 && r.height > 16 &&
                   s.display !== 'none' && s.visibility !== 'hidden' &&
                   r.bottom > 0 && r.top < vh && r.right > 0 && r.left < vw;
          };
          const centerDist = (r) => Math.abs((r.left + r.width/2) - vw/2) + Math.abs((r.top + r.height/2) - vh/2);

          // 中央寄りの大きい動画 → そこから親カードを辿る
          const vids = Array.from(document.querySelectorAll('video'))
            .filter(visible)
            .map(v => ({el: v, rect: v.getBoundingClientRect()}))
            .filter(x => x.rect.width > 120 && x.rect.height > 180)
            .sort((a, b) => centerDist(a.rect) - centerDist(b.rect));
          const v = vids[0]?.el || null;
          if (!v) return null;

          let container = null;
          let n = v;
          for (let i = 0; n && i < 14; i++, n = n.parentElement) {
            const r = n.getBoundingClientRect();
            const links = n.querySelectorAll ? n.querySelectorAll('a[href*="/@"]').length : 0;
            if (r.height > vh * 0.45 && r.width > vw * 0.20 && links > 0) {
              container = n;
              break;
            }
          }
          if (!container) return null;

          const sels = [
            '[data-e2e="like-icon"]',
            '[data-e2e="browse-like-icon"]',
            'button[aria-label*="いいね" i]',
            'button[aria-label*="like" i]',
            '[aria-pressed][aria-label*="いいね" i]',
            '[aria-pressed][aria-label*="like" i]',
          ];
          for (const sel of sels) {
            const els = Array.from(container.querySelectorAll(sel)).filter(visible);
            if (els.length) {
              // すでに押されてる(aria-pressed=true)ならスキップ
              const el = els[0];
              const pressed = el.getAttribute('aria-pressed');
              if (pressed === 'true') {
                return {already_liked: true, src: 'sel:'+sel};
              }
              // クリック可能な祖先 button を優先
              let target = el.closest('button') || el;
              const r = target.getBoundingClientRect();
              return {
                x: r.left + r.width/2,
                y: r.top + r.height/2,
                src: 'sel:'+sel,
                already_liked: false,
              };
            }
          }
          return null;
        }
        """)
    except Exception:
        return None


async def fire_like(page: Page) -> dict:
    """中央の動画カードの「いいね」を物理クリック。失敗してもサイレント。"""
    btn = await _find_like_button(page)
    if not btn:
        return {"ok": False, "reason": "button_not_found"}
    if btn.get("already_liked"):
        return {"ok": False, "reason": "already_liked"}

    try:
        jx = btn["x"] + random.uniform(-3, 3)
        jy = btn["y"] + random.uniform(-3, 3)
        await page.mouse.move(jx, jy, steps=random.randint(10, 18))
        await asyncio.sleep(random.uniform(0.10, 0.25))
        await page.mouse.down()
        await asyncio.sleep(random.uniform(0.04, 0.10))
        await page.mouse.up()
        await asyncio.sleep(random.uniform(0.3, 0.6))
        return {"ok": True, "btn_src": btn.get("src", "")}
    except Exception as e:
        return {"ok": False, "reason": f"click_failed:{e!s:.120}"}


async def get_current_video_info(page: Page) -> dict:
    """
    画面中央の動画を起点に、その動画を含む親コンテナを特定して
    そこ内のリンクから作者UIDを取る(サイドバーを拾わないため)。
    また video.currentSrc を返して「本当に動画が変わったか」を二重判定する。
    """
    try:
        return await page.evaluate(r"""
        () => {
          const vw = innerWidth, vh = innerHeight;
          const visible = (el) => {
            const r = el.getBoundingClientRect();
            const s = getComputedStyle(el);
            return r.width > 5 && r.height > 5 &&
                   s.display !== 'none' && s.visibility !== 'hidden' &&
                   r.bottom > 0 && r.top < vh && r.right > 0 && r.left < vw;
          };
          const centerDist = (r) => Math.abs((r.left + r.width/2) - vw/2) + Math.abs((r.top + r.height/2) - vh/2);
          const hrefToId = (href) => {
            const m = String(href || '').match(/\/@([^/?#]+)/);
            return m ? m[1] : '';
          };

          // 中央寄りの大きい動画
          const vids = Array.from(document.querySelectorAll('video'))
            .filter(visible)
            .map(v => ({el: v, rect: v.getBoundingClientRect()}))
            .filter(x => x.rect.width > 120 && x.rect.height > 180)
            .sort((a, b) => centerDist(a.rect) - centerDist(b.rect));
          const v = vids[0]?.el || null;

          // 動画を含む「フィードカード」コンテナを上に辿って探す
          let container = null;
          if (v) {
            let n = v;
            for (let i = 0; n && i < 14; i++, n = n.parentElement) {
              const r = n.getBoundingClientRect();
              const links = n.querySelectorAll ? n.querySelectorAll('a[href*="/@"]').length : 0;
              if (r.height > vh * 0.45 && r.width > vw * 0.20 && links > 0) {
                container = n;
                break;
              }
            }
          }

          // コンテナ内の @ リンクから profile (動画URLじゃない方) を選ぶ
          let uid = '';
          let pickSrc = '';
          if (container) {
            const anchors = Array.from(container.querySelectorAll('a[href*="/@"]'))
              .filter(visible)
              .map(a => ({href: a.href, id: hrefToId(a.href), rect: a.getBoundingClientRect()}))
              .filter(x => x.id);
            const profiles = anchors.filter(x => !/\/video\//.test(x.href))
              .sort((x, y) => centerDist(x.rect) - centerDist(y.rect));
            if (profiles.length) { uid = profiles[0].id; pickSrc = 'container-profile'; }
            if (!uid) {
              const videos = anchors.filter(x => /\/video\//.test(x.href))
                .sort((x, y) => centerDist(x.rect) - centerDist(y.rect));
              if (videos.length) { uid = videos[0].id; pickSrc = 'container-video'; }
            }
          }
          if (!uid) {
            const m = location.href.match(/\/@([^/?#]+)/);
            if (m) { uid = m[1]; pickSrc = 'location'; }
          }

          return {
            uid: uid || '',
            uid_src: pickSrc,
            url: location.href,
            playing: !!(v && !v.paused && !v.ended && v.readyState > 2),
            currentTime: v ? Number(v.currentTime || 0) : 0,
            duration: v ? Number(v.duration || 0) : 0,
            // 動画ファイル自体の識別子(切り替わったかの真の判定)
            currentSrc: v ? String(v.currentSrc || v.src || '').slice(-80) : '',
            videoCount: vids.length,
          };
        }
        """)
    except Exception as e:
        return {"uid": "", "url": "", "playing": False, "error": str(e)[:200]}


async def _find_next_button(page: Page) -> dict | None:
    """画面右の「次の動画」chevronボタンの中心座標を取る。"""
    try:
        return await page.evaluate(r"""
        () => {
          const vw = innerWidth, vh = innerHeight;
          const visible = (el) => {
            const r = el.getBoundingClientRect();
            const s = getComputedStyle(el);
            return r.width > 16 && r.height > 16 &&
                   s.display !== 'none' && s.visibility !== 'hidden' &&
                   r.bottom > 0 && r.top < vh;
          };
          // aria-label / data-e2e 系から「次」っぽいボタンを探す
          const sels = [
            'button[aria-label*="次" i]',
            'button[aria-label*="next" i]',
            'button[data-e2e*="arrow-right"]',
            'button[data-e2e*="arrow-down"]',
            'button[data-e2e*="next"]',
          ];
          for (const sel of sels) {
            const els = Array.from(document.querySelectorAll(sel)).filter(visible);
            if (els.length) {
              const r = els[0].getBoundingClientRect();
              return {x: r.left + r.width/2, y: r.top + r.height/2, src: 'sel:'+sel};
            }
          }
          // 画面右側に出てるchevron下向きSVGを探す
          const buttons = Array.from(document.querySelectorAll('button, [role="button"]')).filter(visible);
          for (const b of buttons) {
            const r = b.getBoundingClientRect();
            if (r.left < vw * 0.78 || r.right > vw + 5) continue;
            if (r.top < vh * 0.35 || r.top > vh * 0.85) continue;
            const svg = b.querySelector('svg');
            if (!svg) continue;
            // 下向き矢印っぽい path を持つか
            const d = (svg.querySelector('path')?.getAttribute('d') || '');
            if (/[Mm].*[Ll]/.test(d)) {
              return {x: r.left + r.width/2, y: r.top + r.height/2, src: 'right-svg'};
            }
          }
          return null;
        }
        """)
    except Exception:
        return None


async def human_swipe(page: Page) -> dict:
    """
    TikTok For You を次に進める。順番で試す:
      1. 動画の右側に乗ってホイールを1発大きく回す
      2. 効かなかったら次へボタン(chevron)を物理クリック
    どちらも CDP Input 経由で isTrusted=true の本物イベント。
    """
    GET_SRC = """
    () => {
      const vw = innerWidth, vh = innerHeight;
      const dist = (r) => Math.abs((r.left + r.width/2) - vw/2) + Math.abs((r.top + r.height/2) - vh/2);
      const vids = Array.from(document.querySelectorAll('video'))
        .map(v => ({el: v, r: v.getBoundingClientRect()}))
        .filter(x => x.r.width > 120 && x.r.height > 180)
        .sort((a, b) => dist(a.r) - dist(b.r));
      const v = vids[0]?.el;
      return v ? String(v.currentSrc || v.src || '') : '';
    }
    """
    try:
        dims = await page.evaluate("() => ({vw: innerWidth, vh: innerHeight})")
        vw, vh = dims["vw"], dims["vh"]

        before_src = await page.evaluate(GET_SRC)

        # 動画の右側、コントロール群の手前あたり
        cx = vw * random.uniform(0.72, 0.82)
        cy = vh * random.uniform(0.40, 0.60)
        await page.mouse.move(cx, cy, steps=random.randint(10, 18))
        await asyncio.sleep(random.uniform(0.10, 0.28))

        # 1発で大きく回す
        big = random.uniform(900, 1300)
        await page.mouse.wheel(0, big)

        await asyncio.sleep(random.uniform(0.7, 1.1))
        after_src = await page.evaluate(GET_SRC)

        if after_src and after_src != before_src:
            return {"ok": True, "method": "wheel", "dy": round(big, 1)}

        # ホイールで進まなかった → chevronボタンを物理クリック
        btn = await _find_next_button(page)
        if btn:
            jx = btn["x"] + random.uniform(-3, 3)
            jy = btn["y"] + random.uniform(-3, 3)
            await page.mouse.move(jx, jy, steps=random.randint(10, 16))
            await asyncio.sleep(random.uniform(0.08, 0.20))
            await page.mouse.down()
            await asyncio.sleep(random.uniform(0.03, 0.09))
            await page.mouse.up()
            await asyncio.sleep(random.uniform(0.7, 1.0))
            after2_src = await page.evaluate(GET_SRC)
            if after2_src and after2_src != before_src:
                return {"ok": True, "method": "chevron-click", "btn_src": btn.get("src", "")}
            return {"ok": False, "method": "chevron-click-no-advance", "btn_src": btn.get("src", "")}

        return {"ok": False, "method": "no-advance-no-button"}
    except Exception as e:
        return {"ok": False, "method": "error", "error": str(e)[:200]}


async def watch_a_bit(page: Page) -> float:
    """動画を 2.0〜5.5 秒ほど普通に見る。pause guard は入れない。"""
    sec = random.uniform(2.0, 5.5)
    await asyncio.sleep(sec)
    return sec


async def maybe_mouse_jitter(page: Page) -> None:
    """5回に1回くらい、視聴中にマウスを少し動かす(noise)。"""
    if random.random() < 0.2:
        try:
            dims = await page.evaluate("() => ({vw: innerWidth, vh: innerHeight})")
            x = dims["vw"] * random.uniform(0.3, 0.7)
            y = dims["vh"] * random.uniform(0.3, 0.7)
            await page.mouse.move(x, y, steps=random.randint(5, 12))
        except Exception:
            pass


async def main(max_swipes: int) -> None:
    print(f"=== TikTokCollectorStealth probe 起動 ({max_swipes}スワイプまで) ===", flush=True)
    print(f"ログ: {LOG_PATH}", flush=True)

    cfg = load_config()
    algo = (cfg.get("algorithm_stealth") or {})
    rules = (cfg.get("rules") or {})
    max_followers = int(rules.get("max_followers") or 2000)
    enable_candidacy = bool(algo.get("enable_candidacy_check", True))
    enable_like = bool(algo.get("enable_like", True))
    like_probability = float(algo.get("like_probability", 0.05))
    like_min_interval_sec = float(algo.get("like_min_interval_sec", 90))

    past_adopted_uids: set[str] = set()
    if enable_candidacy:
        past_adopted_uids = load_past_adopted_uids(cfg)

    async with async_playwright() as p:
        try:
            browser = await p.chromium.connect_over_cdp(CDP_URL)
        except Exception as e:
            print(f"\nCDP接続失敗: {e}", flush=True)
            print("先に 1_launch_chrome.command を起動してChromeを立ち上げてください。", flush=True)
            sys.exit(1)

        # 既存コンテキストの既存タブを使う
        context = browser.contexts[0] if browser.contexts else await browser.new_context()
        # init script は context 単位で入れる(以降の全ページに適用)
        await context.add_init_script(STEALTH_INIT_JS)

        pages = context.pages
        page = None
        for pg in pages:
            if "tiktok.com" in (pg.url or ""):
                page = pg
                break
        if page is None:
            page = pages[0] if pages else await context.new_page()
            if "tiktok.com" not in (page.url or ""):
                await page.goto("https://www.tiktok.com/", wait_until="domcontentloaded")

        # init script は新規ナビゲーション時に効くので、既存タブには手動注入も入れる
        try:
            await page.evaluate(STEALTH_INIT_JS)
        except Exception:
            pass

        # フィードAPIレスポンス盗聴を仕掛ける(プロフィール開かずに follower 数を得るため)
        _attach_follower_response_cache(page)

        log_event({
            "event": "start",
            "url": page.url,
            "max_swipes": max_swipes,
            "candidacy": {
                "enabled": enable_candidacy,
                "past_adopted_count": len(past_adopted_uids),
                "max_followers": max_followers,
            },
            "like": {
                "enabled": enable_like,
                "probability": like_probability,
                "min_interval_sec": like_min_interval_sec,
            },
        })

        prev_uid = ""
        same_uid_streak = 0
        stuck_warned = False
        last_like_ts = 0.0
        liked_uids: set[str] = set()

        for i in range(1, max_swipes + 1):
            await maybe_mouse_jitter(page)
            watched = await watch_a_bit(page)
            info_before = await get_current_video_info(page)

            swipe = await human_swipe(page)

            # スワイプ後、フィード切り替えを待ってから状態取得
            await asyncio.sleep(random.uniform(0.6, 1.4))
            info_after = await get_current_video_info(page)

            uid_after = info_after.get("uid", "")
            src_before = info_before.get("currentSrc", "")
            src_after = info_after.get("currentSrc", "")
            video_changed = bool(src_after) and src_after != src_before

            if uid_after and uid_after == prev_uid:
                same_uid_streak += 1
            else:
                same_uid_streak = 0
            prev_uid = uid_after

            # 候補性判定: 過去採用でない & フォロワー < max_followers
            follower = get_follower_count_from_cache(page, uid_after) if uid_after else None
            is_past_adopted = bool(uid_after) and uid_after in past_adopted_uids
            is_candidate = (
                enable_candidacy
                and bool(uid_after)
                and not is_past_adopted
                and follower is not None
                and follower < max_followers
            )

            log_event({
                "event": "swipe",
                "i": i,
                "watched_sec": round(watched, 2),
                "before_uid": info_before.get("uid", ""),
                "after_uid": uid_after,
                "uid_src": info_after.get("uid_src", ""),
                "video_changed": video_changed,
                "playing": info_after.get("playing"),
                "duration": info_after.get("duration"),
                "url": info_after.get("url", ""),
                "swipe_ok": swipe.get("ok"),
                "swipe_method": swipe.get("method", ""),
                "same_uid_streak": same_uid_streak,
                "follower_count": follower,
                "past_adopted": is_past_adopted,
                "is_candidate": is_candidate,
            })

            if same_uid_streak >= 2 and not stuck_warned:
                log_event({"event": "warn_feed_stuck", "i": i, "uid": uid_after})
                stuck_warned = True

            # like 発火: 候補 & 確率通過 & interval OK & まだ like していない uid
            if (
                enable_like
                and is_candidate
                and uid_after not in liked_uids
                and random.random() < like_probability
                and (time.monotonic() - last_like_ts) >= like_min_interval_sec
            ):
                like_result = await fire_like(page)
                if like_result.get("ok"):
                    last_like_ts = time.monotonic()
                    liked_uids.add(uid_after)
                log_event({
                    "event": "like_attempt",
                    "i": i,
                    "uid": uid_after,
                    "follower_count": follower,
                    "result": like_result,
                })

            # 次のスワイプまでの待機。ばらつき大きめ
            await asyncio.sleep(random.uniform(1.8, 6.0))

            # 20スワイプごとにロング休憩
            if i % 20 == 0:
                rest = random.uniform(30, 90)
                log_event({"event": "long_rest", "i": i, "rest_sec": round(rest, 1)})
                await asyncio.sleep(rest)

        log_event({
            "event": "done",
            "total": max_swipes,
            "liked_count": len(liked_uids),
        })


if __name__ == "__main__":
    n = 60
    if len(sys.argv) > 1:
        try:
            n = int(sys.argv[1])
        except ValueError:
            pass
    try:
        asyncio.run(main(n))
    except KeyboardInterrupt:
        print("\n中断されました。", flush=True)
