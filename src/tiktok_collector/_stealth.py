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
    """文書全体から visible な like 系要素を収集 → 中央動画のサイドバー位置に
    最も近いものを選ぶ。古い実装はコンテナ(@リンクを含む親)前提だったが、
    TikTok の DOM 改修で video とサイドバーが別ブランチに分かれるケースがあり、
    container=null で button_not_found になっていた。
    """
    try:
        return await page.evaluate(r"""
        () => {
          const vw = innerWidth, vh = innerHeight;
          const visible = (el) => {
            if (!el) return false;
            const r = el.getBoundingClientRect();
            const s = getComputedStyle(el);
            return r.width > 16 && r.height > 16 &&
                   s.display !== 'none' && s.visibility !== 'hidden' &&
                   r.bottom > 0 && r.top < vh && r.right > 0 && r.left < vw;
          };
          // 中央動画を特定
          const vids = Array.from(document.querySelectorAll('video'))
            .filter(visible)
            .map(v => ({el: v, rect: v.getBoundingClientRect()}))
            .filter(x => x.rect.width > 120 && x.rect.height > 180);
          if (!vids.length) return null;
          vids.sort((a, b) => {
            const dA = Math.abs((a.rect.left + a.rect.width/2) - vw/2) + Math.abs((a.rect.top + a.rect.height/2) - vh/2);
            const dB = Math.abs((b.rect.left + b.rect.width/2) - vw/2) + Math.abs((b.rect.top + b.rect.height/2) - vh/2);
            return dA - dB;
          });
          const vr = vids[0].rect;

          // セレクタ候補。TikTok の data-e2e / aria-label は世代で表記揺れあり。
          const selectors = [
            '[data-e2e="like-icon"]',
            '[data-e2e="browse-like-icon"]',
            '[data-e2e*="like-icon"]',
            'button[aria-label*="いいね" i]',
            'button[aria-label*="like" i]',
            'button[aria-label*="赞" i]',
            '[role="button"][aria-label*="いいね" i]',
            '[role="button"][aria-label*="like" i]',
            'span[data-e2e="like-icon"]',
          ];
          const candidates = [];
          for (const sel of selectors) {
            try {
              for (const el of document.querySelectorAll(sel)) {
                if (!visible(el)) continue;
                candidates.push({el, sel, rect: el.getBoundingClientRect()});
              }
            } catch(e) {}
          }
          if (!candidates.length) return null;

          // 中央動画の「右サイドバー」位置(For You のレイアウト前提)に最も近いものを優先。
          // 動画の左側 / 動画から大きく離れたものはコメント欄や別ページの like なのでペナルティ。
          const targetX = vr.right + 30;
          const targetY = vr.top + vr.height * 0.55;
          candidates.forEach(c => {
            const cx = c.rect.left + c.rect.width / 2;
            const cy = c.rect.top + c.rect.height / 2;
            c.score = Math.abs(cx - targetX) + Math.abs(cy - targetY);
            if (cx < vr.right - 30) c.score += 1000;       // 動画より左 = サイドバー外
            if (cy < vr.top - 80 || cy > vr.bottom + 80) c.score += 500; // 動画の縦範囲外
          });
          candidates.sort((a, b) => a.score - b.score);
          const best = candidates[0];

          // aria-pressed は要素 or 親 3 階層まで遡って判定(TikTok は入れ子構造を使う)
          let pressed = null;
          let n = best.el;
          for (let i = 0; n && i < 4; i++, n = n.parentElement) {
            if (!n.getAttribute) continue;
            const ap = n.getAttribute('aria-pressed');
            if (ap === 'true' || ap === 'false') {
              pressed = ap;
              break;
            }
          }
          if (pressed === 'true') {
            return {already_liked: true, src: 'sel:' + best.sel};
          }

          // クリック対象: 包む button があればそちらを優先(hit test 安定化)
          const target = best.el.closest('button') || best.el;
          const r = target.getBoundingClientRect();
          const cx = r.left + r.width / 2;
          const cy = r.top + r.height / 2;
          // overlay でクリックが阻害されないかを elementFromPoint で確認
          let top = null;
          try { top = document.elementFromPoint(cx, cy); } catch(e) {}
          const clickable = !top || top === target || target.contains(top) ||
                            (top.contains && top.contains(target));
          return {
            x: cx, y: cy,
            src: 'sel:' + best.sel,
            already_liked: false,
            clickable: clickable,
          };
        }
        """)
    except Exception:
        return None


async def _verify_liked(page: Page) -> bool:
    """中央動画サイドバーの like ボタン aria-pressed=true を確認。クリック直後の
    UI 反映ラグを許容するため、呼び出し側で軽くリトライする。"""
    try:
        return bool(await page.evaluate(r"""
        () => {
          const vw = innerWidth, vh = innerHeight;
          const visible = (el) => {
            if (!el) return false;
            const r = el.getBoundingClientRect();
            const s = getComputedStyle(el);
            return r.width > 16 && r.height > 16 && s.display !== 'none' && s.visibility !== 'hidden';
          };
          const vids = Array.from(document.querySelectorAll('video'))
            .filter(visible)
            .map(v => ({el: v, rect: v.getBoundingClientRect()}))
            .filter(x => x.rect.width > 120 && x.rect.height > 180);
          if (!vids.length) return false;
          vids.sort((a, b) => Math.abs(a.rect.left - vw/2) - Math.abs(b.rect.left - vw/2));
          const vr = vids[0].rect;
          const sels = [
            '[data-e2e="like-icon"]',
            '[data-e2e="browse-like-icon"]',
            'button[aria-label*="いいね" i]',
            'button[aria-label*="like" i]',
          ];
          for (const sel of sels) {
            for (const el of document.querySelectorAll(sel)) {
              if (!visible(el)) continue;
              const r = el.getBoundingClientRect();
              if (r.left < vr.right - 30) continue;  // サイドバー以外は無視
              let n = el;
              for (let i = 0; n && i < 4; i++, n = n.parentElement) {
                if (n.getAttribute && n.getAttribute('aria-pressed') === 'true') return true;
              }
            }
          }
          return false;
        }
        """))
    except Exception:
        return False


async def fire_like(page: Page) -> dict:
    """中央動画カードの「いいね」を物理クリック。フォロー はしない。
    クリック後は aria-pressed=true を確認(最大 ~600ms リトライ)。"""
    btn = await _find_like_button(page)
    if not btn:
        return {"ok": False, "reason": "button_not_found"}
    if btn.get("already_liked"):
        return {"ok": False, "reason": "already_liked"}
    if btn.get("clickable") is False:
        return {"ok": False, "reason": "button_obscured"}
    try:
        jx = btn["x"] + random.uniform(-3, 3)
        jy = btn["y"] + random.uniform(-3, 3)
        await page.mouse.move(jx, jy, steps=random.randint(10, 18))
        await asyncio.sleep(random.uniform(0.10, 0.25))
        await page.mouse.down()
        await asyncio.sleep(random.uniform(0.04, 0.10))
        await page.mouse.up()
        await asyncio.sleep(random.uniform(0.3, 0.6))
    except Exception as e:
        return {"ok": False, "reason": f"click_failed:{e!s:.120}"}

    # クリック後の UI 反映を最大 ~600ms 待つ。失敗しても like 自体は飛んでる可能性が
    # あるが、verify=False はログ用に明示する。
    for _ in range(3):
        if await _verify_liked(page):
            return {"ok": True, "btn_src": btn.get("src", "")}
        await asyncio.sleep(0.2)
    return {"ok": False, "reason": "click_no_verify", "btn_src": btn.get("src", "")}
