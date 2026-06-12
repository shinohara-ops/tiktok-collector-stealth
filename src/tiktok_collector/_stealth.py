"""
stealth 共通部品。probe.py と本体パイプライン(runner.py / scraper.py)で共有する。

含めるもの:
  - STEALTH_INIT_JS: Page Visibility を visible に固定して WebDriver 痕跡を消す init script
  - human_swipe: mouse.wheel ベースのスワイプ。失敗時 chevron クリックに fallback
  - fire_like: 中央動画の「いいね」ボタンを物理クリック。aria-pressed=true はスキップ

すべて async 関数 + 引数 page だけ。Scraper クラスに依存しない。
"""
from __future__ import annotations

import asyncio
import random

from playwright.async_api import Page


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


_GET_CENTER_VIDEO_SRC_JS = r"""
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


async def _find_next_button(page: Page) -> dict | None:
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
          const buttons = Array.from(document.querySelectorAll('button, [role="button"]')).filter(visible);
          for (const b of buttons) {
            const r = b.getBoundingClientRect();
            if (r.left < vw * 0.78 || r.right > vw + 5) continue;
            if (r.top < vh * 0.35 || r.top > vh * 0.85) continue;
            const svg = b.querySelector('svg');
            if (!svg) continue;
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
    """TikTok For You を次へ進める。wheel → chevron click → ArrowDown の順で試す。
    すべて CDP Input 経由なので isTrusted=true。

    タイミング:
      普通のユーザーが興味ない動画を 0.5〜1.5 秒でスワイプする挙動を模倣する。
      検知耐性は probe 60/60 完走で確認済み(速いスワイプ自体は不審ではない)。"""
    try:
        dims = await page.evaluate("() => ({vw: innerWidth, vh: innerHeight})")
        vw, vh = dims["vw"], dims["vh"]
        before_src = await page.evaluate(_GET_CENTER_VIDEO_SRC_JS)

        cx = vw * random.uniform(0.72, 0.82)
        cy = vh * random.uniform(0.40, 0.60)
        await page.mouse.move(cx, cy, steps=random.randint(5, 10))
        await asyncio.sleep(random.uniform(0.04, 0.12))
        big = random.uniform(900, 1300)
        await page.mouse.wheel(0, big)
        # スワイプ後の DOM 切り替わり待ち。ここを短くすると一番効くが
        # 短すぎると after_src 取得時にまだ前動画のままで wheel 失敗扱いに
        # なるので 0.30〜0.45 で安定。
        await asyncio.sleep(random.uniform(0.30, 0.45))
        after_src = await page.evaluate(_GET_CENTER_VIDEO_SRC_JS)
        if after_src and after_src != before_src:
            return {"ok": True, "method": "wheel"}

        btn = await _find_next_button(page)
        if btn:
            jx = btn["x"] + random.uniform(-3, 3)
            jy = btn["y"] + random.uniform(-3, 3)
            await page.mouse.move(jx, jy, steps=random.randint(5, 9))
            await asyncio.sleep(random.uniform(0.04, 0.10))
            await page.mouse.down()
            await asyncio.sleep(random.uniform(0.02, 0.06))
            await page.mouse.up()
            await asyncio.sleep(random.uniform(0.30, 0.50))
            after2_src = await page.evaluate(_GET_CENTER_VIDEO_SRC_JS)
            if after2_src and after2_src != before_src:
                return {"ok": True, "method": "chevron-click"}

        try:
            await page.keyboard.press("ArrowDown")
            await asyncio.sleep(random.uniform(0.30, 0.50))
            return {"ok": True, "method": "arrow-down-fallback"}
        except Exception:
            pass
        return {"ok": False, "method": "no-advance"}
    except Exception as e:
        return {"ok": False, "method": "error", "error": str(e)[:200]}


async def _find_like_button(page: Page) -> dict | None:
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
              const el = els[0];
              const pressed = el.getAttribute('aria-pressed');
              if (pressed === 'true') {
                return {already_liked: true, src: 'sel:'+sel};
              }
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
    """中央動画カードの「いいね」を物理クリック。フォロー はしない。"""
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
