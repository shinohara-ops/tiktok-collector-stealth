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


async def human_swipe(page: Page) -> dict:
    """TikTok For You を次の動画へ進める。**下方向のみ**保証。

    優先順位:
      1. CDP mouse wheel(deltaY > 0 = 下スクロール = 次の動画)
      2. ArrowDown キー(下方向、確実)

    chevron-click(右側矢印ボタン)は廃止。TikTok の DOM 改修で「次」と「前」
    のボタンが同じ data-e2e / aria-label セットを使うケースがあり、検出が
    間違って「前へ」を押してしまうと画面上で 1 つ戻ってしまう。

    検知耐性は probe 60/60 完走で確認済み。普通のユーザーが興味ない動画を
    0.5〜1.5 秒でスワイプする挙動を模倣する。"""
    try:
        dims = await page.evaluate("() => ({vw: innerWidth, vh: innerHeight})")
        vw, vh = dims["vw"], dims["vh"]
        before_src = await page.evaluate(_GET_CENTER_VIDEO_SRC_JS)

        cx = vw * random.uniform(0.72, 0.82)
        cy = vh * random.uniform(0.40, 0.60)
        await page.mouse.move(cx, cy, steps=random.randint(5, 10))
        await asyncio.sleep(random.uniform(0.04, 0.12))
        big = random.uniform(900, 1300)  # 正の値 = 下方向(次の動画)
        await page.mouse.wheel(0, big)
        # スワイプ後の DOM 切替待ち。短すぎると after_src がまだ前動画
        # と同じに見えて wheel 失敗扱いになり、fallback に流れる。
        await asyncio.sleep(random.uniform(0.55, 0.70))
        after_src = await page.evaluate(_GET_CENTER_VIDEO_SRC_JS)
        # src が空のときは動画ロード中 → 成功扱い(誤った fallback を防ぐ)。
        if not after_src or after_src != before_src:
            return {"ok": True, "method": "wheel"}

        # wheel が効かない場合のみ ArrowDown(キーボード操作で次の動画へ)
        try:
            await page.keyboard.press("ArrowDown")
            await asyncio.sleep(random.uniform(0.40, 0.60))
            after2_src = await page.evaluate(_GET_CENTER_VIDEO_SRC_JS)
            if not after2_src or after2_src != before_src:
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
