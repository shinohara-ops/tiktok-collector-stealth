from __future__ import annotations

import re
from pathlib import Path
from datetime import datetime
from playwright.async_api import Page, BrowserContext
from .models import Candidate


def clean_id(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "", s or "")


def id_from_url(url: str) -> str:
    m = re.search(r"/@([^/?#]+)", str(url or ""))
    return clean_id(m.group(1)) if m else ""


def parse_count(text: str):
    if not text:
        return None
    s = str(text).strip().replace(",", "").replace("，", "")
    m = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*(万|億|K|k|M|m)?", s)
    if not m:
        return None
    n = float(m.group(1))
    unit = m.group(2) or ""
    if unit == "万":
        n *= 10000
    elif unit == "億":
        n *= 100000000
    elif unit.lower() == "k":
        n *= 1000
    elif unit.lower() == "m":
        n *= 1000000
    return int(n)


class TikTokScraper:
    def __init__(self, screenshot_dir: str):
        self.screenshot_dir = Path(screenshot_dir)
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)

    async def current_candidate(self, page: Page) -> Candidate | None:
        data = await page.evaluate(r"""
        () => {
          const vw = window.innerWidth;
          const vh = window.innerHeight;

          const visible = (el) => {
            if (!el) return false;
            const r = el.getBoundingClientRect();
            const s = window.getComputedStyle(el);
            return r.width > 10 && r.height > 10 &&
                   s.display !== 'none' && s.visibility !== 'hidden' &&
                   r.bottom > 0 && r.top < vh && r.right > 0 && r.left < vw;
          };

          const centerDist = (r) => {
            const cx = r.left + r.width / 2;
            const cy = r.top + r.height / 2;
            return Math.abs(cx - vw / 2) + Math.abs(cy - vh / 2);
          };

          const hrefToId = (href) => {
            const m = String(href || '').match(/\/@([^/?#]+)/);
            return m ? m[1] : '';
          };

          const videos = Array.from(document.querySelectorAll('video'))
            .filter(visible)
            .map(v => ({ el: v, rect: v.getBoundingClientRect() }))
            .filter(x => x.rect.width > 120 && x.rect.height > 180)
            .sort((a, b) => centerDist(a.rect) - centerDist(b.rect));

          const video = videos[0] && videos[0].el;
          const vr = video ? video.getBoundingClientRect() : {left: 0, top: 0, right: vw, bottom: vh, width: vw, height: vh};

          const inCurrentZone = (r) => {
            return r.right > Math.max(0, vr.left - 360) &&
                   r.left < Math.min(vw, vr.right + 520) &&
                   r.bottom > Math.max(0, vr.top - 320) &&
                   r.top < Math.min(vh, vr.bottom + 360);
          };

          let container = null;
          if (video) {
            let n = video;
            let best = null;
            for (let i = 0; n && i < 12; i++, n = n.parentElement) {
              const r = n.getBoundingClientRect();
              const t = (n.innerText || n.textContent || '').trim();
              const links = n.querySelectorAll ? n.querySelectorAll('a[href*="/@"]').length : 0;
              if (r.height > vh * 0.45 && r.width > vw * 0.25 && links > 0) {
                best = n;
                break;
              }
              if (t && links > 0) best = n;
            }
            container = best;
          }

          const scope = container || document;

          const anchors = Array.from(scope.querySelectorAll('a[href*="/@"]'))
            .filter(visible)
            .map(a => ({
              href: a.href,
              id: hrefToId(a.href),
              rect: a.getBoundingClientRect(),
              text: (a.innerText || a.textContent || '').trim()
            }))
            .filter(x => x.id && inCurrentZone(x.rect));

          const profileLinks = anchors
            .filter(x => !/\/video\//.test(x.href))
            .sort((x, y) => centerDist(x.rect) - centerDist(y.rect));

          const videoLinks = anchors
            .filter(x => /\/video\//.test(x.href))
            .sort((x, y) => centerDist(x.rect) - centerDist(y.rect));

          const urlId = hrefToId(location.href);
          const urlVideo = location.href.includes('/video/') ? location.href : '';

          let profile = profileLinks[0] || null;
          let videoLink = videoLinks[0] || null;

          let uniqueId = profile ? profile.id : (videoLink ? videoLink.id : '');
          if (!uniqueId && urlId && urlVideo) uniqueId = urlId;

          let postUrl = '';
          if (videoLink && videoLink.href && (!uniqueId || videoLink.id === uniqueId)) postUrl = videoLink.href;
          else if (urlVideo && (!uniqueId || urlId === uniqueId)) postUrl = urlVideo;

          const profileUrl = uniqueId ? `https://www.tiktok.com/@${uniqueId}` : '';

          let text = '';
          if (container) text = (container.innerText || container.textContent || '').trim();
          if (!text && video) {
            let n = video;
            for (let i = 0; n && i < 9; i++, n = n.parentElement) {
              const t = (n.innerText || n.textContent || '').trim();
              if (t && t.length > text.length && t.length < 3000) text = t;
            }
          }
          if (!text) text = (document.body.innerText || '').slice(0, 3000);

          const compact = (text || '').replace(/\s+/g, '');
          const isAd = /広告|スポンサー|Sponsored|Promoted|プロモーション|PR投稿|タイアップ|提供/.test(compact);

          return {
            uniqueId,
            profileUrl,
            postUrl,
            displayName: profile && profile.text ? profile.text.split('\n')[0].trim() : uniqueId,
            text,
            isAd,
            pageUrl: location.href
          };
        }
        """)

        unique_id = clean_id((data or {}).get("uniqueId", ""))
        if not unique_id:
            m = re.search(r"/@([^/?#]+)", page.url)
            if m and "/video/" in page.url:
                unique_id = clean_id(m.group(1))

        if not unique_id:
            return None

        body_text = ((data or {}).get("text") or "")[:3000]
        hashtags = " ".join(re.findall(r"#([\wぁ-んァ-ン一-龯ー0-9A-Za-z]+)", body_text))
        display_name = (data or {}).get("displayName") or unique_id
        profile_url = (data or {}).get("profileUrl") or f"https://www.tiktok.com/@{unique_id}"
        post_url = (data or {}).get("postUrl") or ""

        post_id = id_from_url(post_url)
        if post_url and post_id and post_id != unique_id:
            post_url = ""

        return Candidate(
            unique_id=unique_id,
            display_name=display_name,
            profile_url=profile_url,
            post_url=post_url,
            hashtags=hashtags,
            caption=body_text[:500],
            is_ad=bool((data or {}).get("isAd", False)),
        )

    async def enrich_profile(self, context: BrowserContext, candidate: Candidate) -> Candidate:
        """
        昨日の拡張機能でできていたローカル除外に近づけるため、
        投稿画面ではなくプロフィールページを開いて、フォロワー数/紹介文/フォロー中を取得する。
        """
        page = await context.new_page()
        try:
            await page.goto(candidate.profile_url, wait_until="domcontentloaded", timeout=15000)
            await page.wait_for_timeout(2500)

            data = await page.evaluate(r"""
            () => {
              const bodyText = (document.body.innerText || '').trim();

              const visible = (el) => {
                if (!el) return false;
                const r = el.getBoundingClientRect();
                const s = window.getComputedStyle(el);
                return r.width > 5 && r.height > 5 && s.display !== 'none' && s.visibility !== 'hidden';
              };

              const texts = Array.from(document.querySelectorAll('button, [role="button"], span, div'))
                .filter(visible)
                .map(el => (el.innerText || el.textContent || '').trim())
                .filter(Boolean)
                .slice(0, 500);

              const compactTexts = texts.map(t => t.replace(/\s+/g, ''));

              // プロフィールのフォロー数ラベル「フォロー中」を誤検知しない。
              // フォロー済み判定は、アクションボタンの「メッセージ/Message」だけに絞る。
              const isFollowing = false;
const isAd = /広告|スポンサー|Sponsored|Promoted|プロモーション|PR投稿|タイアップ|提供/.test(bodyText.replace(/\s+/g, ''));

              return { bodyText, texts, isFollowing: false, isAd };
            }
            """)

            body_text = (data or {}).get("bodyText", "") or ""
            candidate.profile_checked = True
            candidate.is_following = candidate.is_following
            candidate.is_ad = candidate.is_ad or bool((data or {}).get("isAd", False))

            # プロフィール紹介文は丸ごと入れる。NGワード/未成年/所属/外国語判定の対象にする
            candidate.signature = body_text[:800]

            # 表示名の補助
            lines = [x.strip() for x in body_text.splitlines() if x.strip()]
            if lines and (not candidate.display_name or candidate.display_name == candidate.unique_id):
                candidate.display_name = lines[0][:80]

            # フォロワー数抽出
            # 日本語UI: 1,234 フォロワー / 1.2万 フォロワー
            m = re.search(r"([0-9０-９,.，]+(?:\.[0-9]+)?\s*(?:万|億|K|k|M|m)?)\s*(?:フォロワー|Followers|followers)", body_text)
            if not m:
                # テキストが「フォロワー」の前後で分かれるケース
                parts = re.split(r"\s+|\n", body_text)
                for i, part in enumerate(parts):
                    if "フォロワー" in part or part.lower() == "followers":
                        if i > 0:
                            m = re.match(r"(.+)", parts[i - 1])
                            break
            if m:
                candidate.follower_count = parse_count(m.group(1))

            # プロフィールページ内から投稿URLを拾える場合だけ補完
            if not candidate.post_url:
                try:
                    post_url = await page.evaluate(r"""
                    () => {
                      const hrefs = Array.from(document.querySelectorAll('a[href*="/video/"]')).map(a => a.href);
                      return hrefs[0] || '';
                    }
                    """)
                    if post_url and id_from_url(post_url) == candidate.unique_id:
                        candidate.post_url = post_url
                except Exception:
                    pass

            return candidate
        except Exception:
            return candidate
        finally:
            try:
                await page.close()
            except Exception:
                pass


    async def detect_feed_following_dom(self, page: Page) -> bool:
        try:
            result = await page.evaluate("""
            () => {
              const vw = window.innerWidth;
              const vh = window.innerHeight;

              const visible = (el) => {
                if (!el) return false;
                const r = el.getBoundingClientRect();
                const s = window.getComputedStyle(el);
                return r.width > 2 && r.height > 2 &&
                       s.display !== 'none' &&
                       s.visibility !== 'hidden' &&
                       r.bottom > 0 && r.top < vh &&
                       r.right > 0 && r.left < vw;
              };

              const norm = (s) => String(s || '')
                .replace(/\\s+/g, '')
                .replace(/[＋+]/g, '+')
                .toLowerCase();

              const getAttrs = (el) => {
                const out = [];
                for (const a of Array.from(el.attributes || [])) {
                  out.push(`${a.name}=${a.value}`);
                }
                return out.join(' ');
              };

              const isRightAvatarArea = (r) => {
                return r.left > vw * 0.58 &&
                       r.right < vw * 1.02 &&
                       r.top > vh * 0.12 &&
                       r.top < vh * 0.56;
              };

              const elems = Array.from(document.querySelectorAll('button, [role="button"], a, svg, path, div, span'))
                .filter(visible)
                .map(el => {
                  const r = el.getBoundingClientRect();
                  const parent = el.parentElement;
                  const ptxt = parent ? (parent.innerText || parent.textContent || '') : '';
                  return {
                    tag: el.tagName,
                    text: norm(el.innerText || el.textContent || ''),
                    aria: norm(el.getAttribute('aria-label') || ''),
                    title: norm(el.getAttribute('title') || ''),
                    attrs: norm(getAttrs(el)),
                    parentText: norm(ptxt),
                    cls: norm(el.className || ''),
                    r: {left:r.left, top:r.top, right:r.right, bottom:r.bottom, width:r.width, height:r.height}
                  };
                })
                .filter(x => isRightAvatarArea(x.r));

              for (const x of elems) {
                const blob = `${x.text} ${x.aria} ${x.title} ${x.attrs} ${x.cls}`;
                if (
                  blob.includes('following') ||
                  blob.includes('followed') ||
                  blob.includes('unfollow') ||
                  blob.includes('フォロー中') ||
                  blob.includes('フォロー済') ||
                  blob.includes('チェック') ||
                  blob.includes('check')
                ) {
                  return {following:true, reason:'dom-following-text', sample: blob.slice(0, 160)};
                }
              }

              for (const x of elems) {
                const blob = `${x.text} ${x.aria} ${x.title} ${x.attrs} ${x.cls}`;
                if (
                  blob.includes('follow') ||
                  blob.includes('フォロー') ||
                  blob.includes('plus') ||
                  blob.includes('add') ||
                  blob.includes('追加') ||
                  blob.includes('+')
                ) {
                  if (
                    !blob.includes('following') &&
                    !blob.includes('followed') &&
                    !blob.includes('unfollow') &&
                    !blob.includes('フォロー中') &&
                    !blob.includes('フォロー済')
                  ) {
                    return {following:false, reason:'dom-follow-button', sample: blob.slice(0, 160)};
                  }
                }
              }

              for (const x of elems.filter(e => e.tag === 'svg' || e.tag === 'path')) {
                const blob = `${x.attrs} ${x.cls} ${x.parentText}`;
                if (blob.includes('check') || blob.includes('following') || blob.includes('followed') || blob.includes('フォロー中')) {
                  return {following:true, reason:'dom-svg-check', sample: blob.slice(0, 160)};
                }
              }

              return {following:false, reason:'dom-unknown', sample: elems.slice(0,5).map(x => `${x.tag}:${x.text}:${x.aria}:${x.attrs}`).join('|').slice(0,200)};
            }
            """)
            return bool(result and result.get("following"))
        except Exception:
            return False




    async def detect_follow_state_local(self, page: Page) -> str:
        """
        v8 following-only gate.
        API/GPT/プロフィール遷移なし。
        右側アイコン列DOMでフォロー中チェックpath/tokenが取れたら following。
        それ以外は not_following 扱い。
        """
        try:
            result = await page.evaluate("""
            () => {
              const vw = window.innerWidth;
              const vh = window.innerHeight;

              const visible = (el) => {
                if (!el) return false;
                const r = el.getBoundingClientRect();
                const s = window.getComputedStyle(el);
                return r.width > 1 && r.height > 1 &&
                       s.display !== 'none' &&
                       s.visibility !== 'hidden' &&
                       r.bottom > 0 && r.top < vh &&
                       r.right > 0 && r.left < vw;
              };

              const norm = (s) => String(s || '')
                .replace(/\s+/g, '')
                .replace(/[＋+]/g, '+')
                .toLowerCase();

              const attrs = (el) => Array.from(el.attributes || []).map(a => `${a.name}=${a.value}`).join(' ');

              const checkPathLike = (raw) => {
                const d = norm(raw);
                return (
                  (d.includes('m436.08') && d.includes('l23.0642.14') && d.includes('l436.08z')) ||
                  (d.includes('436.08') && d.includes('23.06') && d.includes('42.14') && d.includes('28.7')) ||
                  (d.includes('l23.06') && d.includes('42.14') && d.includes('l43')) ||
                  (d.includes('clip-rule=evenodd') && d.includes('436.08') && d.includes('42.14'))
                );
              };

              const inRightRail = (r) => {
                return r.left > vw * 0.50 &&
                       r.right < vw * 1.03 &&
                       r.top > vh * 0.04 &&
                       r.top < vh * 0.90;
              };

              const nodes = Array.from(document.querySelectorAll('button, [role="button"], a, svg, path, div, span'))
                .filter(visible)
                .map(el => {
                  const r = el.getBoundingClientRect();
                  const pathD = String(el.tagName || '').toLowerCase() === 'path' ? (el.getAttribute('d') || '') : '';
                  const childPathD = el.querySelectorAll ? Array.from(el.querySelectorAll('path')).map(p => p.getAttribute('d') || '').join(' ') : '';
                  const blob = norm([
                    el.tagName || '',
                    el.innerText || '',
                    el.textContent || '',
                    el.getAttribute('aria-label') || '',
                    el.getAttribute('title') || '',
                    el.className || '',
                    attrs(el),
                    pathD,
                    childPathD
                  ].join(' '));
                  return {r, blob, path: norm(pathD || childPathD)};
                })
                .filter(x => inRightRail(x.r));

              for (const x of nodes) {
                if (checkPathLike(x.path) || checkPathLike(x.blob)) {
                  return {state:'following', reason:'right-rail-check-path'};
                }
              }

              for (const x of nodes) {
                const b = x.blob;
                if (
                  b.includes('following') ||
                  b.includes('followed') ||
                  b.includes('unfollow') ||
                  b.includes('フォロー中') ||
                  b.includes('フォロー済') ||
                  b.includes('フォロー解除')
                ) {
                  return {state:'following', reason:'right-rail-following-token'};
                }
              }

              return {state:'not_following', reason:'unknown_as_not_following'};
            }
            """)

            state = (result or {}).get("state")
            reason = (result or {}).get("reason", "")

            try:
                from pathlib import Path as _Path
                from datetime import datetime as _dt
                import json as _json
                _Path("data").mkdir(exist_ok=True)
                with open("data/follow_state_live_debug.jsonl", "a", encoding="utf-8") as f:
                    f.write(_json.dumps({
                        "ts": _dt.now().isoformat(),
                        "state": state,
                        "reason": reason
                    }, ensure_ascii=False) + "\n")
            except Exception:
                pass

            if state == "following":
                return "following"
            return "not_following"

        except Exception:
            # エラー時はAPI消費を優先するならnot_following。
            # ただしログは残す。
            try:
                from pathlib import Path as _Path
                from datetime import datetime as _dt
                import json as _json
                _Path("data").mkdir(exist_ok=True)
                with open("data/follow_state_live_debug.jsonl", "a", encoding="utf-8") as f:
                    f.write(_json.dumps({
                        "ts": _dt.now().isoformat(),
                        "state": "not_following",
                        "reason": "error_as_not_following"
                    }, ensure_ascii=False) + "\n")
            except Exception:
                pass
            return "not_following"



    def attach_follower_response_cache(self, page):
        """TikTokフィードAPIレスポンスからauthorStats/followerCountをキャッシュする。プロフィールは開かない。"""
        try:
            if getattr(page, "_follower_cache_attached", False):
                return
            setattr(page, "_follower_cache_attached", True)
            setattr(page, "_follower_count_cache", {})
        except Exception:
            return

        import asyncio

        def _debug(payload):
            try:
                import json
                from pathlib import Path
                from datetime import datetime
                Path("data").mkdir(exist_ok=True)
                payload["ts"] = datetime.now().isoformat()
                with open("data/follower_pipeline_debug.jsonl", "a", encoding="utf-8") as f:
                    f.write(json.dumps(payload, ensure_ascii=False) + "\n")
            except Exception:
                pass

        def pick_uid(obj):
            if not isinstance(obj, dict):
                return ""
            for k in ["uniqueId", "unique_id", "id", "nickname"]:
                v = obj.get(k)
                if isinstance(v, str) and v:
                    return v.replace("@", "")
            return ""

        def pick_count(obj):
            if not isinstance(obj, dict):
                return None
            for k in ["followerCount", "follower_count", "followers", "fans", "fansCount"]:
                v = obj.get(k)
                try:
                    if v is not None and str(v).strip() != "":
                        n = int(float(str(v).replace(",", "")))
                        if 0 <= n < 1000000000:
                            return n
                except Exception:
                    pass
            return None

        def walk(obj, cache, depth=0):
            if depth > 12 or obj is None:
                return 0
            found = 0
            if isinstance(obj, list):
                for x in obj:
                    found += walk(x, cache, depth + 1)
                return found
            if not isinstance(obj, dict):
                return 0

            author = obj.get("author") or obj.get("authorInfo") or obj.get("user") or {}
            stats = obj.get("authorStats") or obj.get("stats") or {}
            if isinstance(author, dict):
                uid = pick_uid(author)
                cnt = pick_count(stats) or pick_count(author.get("stats") or {}) or pick_count(author.get("authorStats") or {})
                if uid and cnt is not None:
                    cache[uid] = cnt
                    found += 1

            uid2 = pick_uid(obj)
            cnt2 = pick_count(obj.get("authorStats") or {}) or pick_count(obj.get("stats") or {})
            if uid2 and cnt2 is not None:
                cache[uid2] = cnt2
                found += 1

            for v in obj.values():
                if isinstance(v, (dict, list)):
                    found += walk(v, cache, depth + 1)
            return found

        async def handle_response(response):
            try:
                url = response.url or ""
                if "tiktok.com" not in url:
                    return
                if "/api/" not in url and "item_list" not in url and "recommend" not in url and "feed" not in url:
                    return
                try:
                    data = await response.json()
                except Exception:
                    return
                cache = getattr(page, "_follower_count_cache", {}) or {}
                before = len(cache)
                found = walk(data, cache)
                setattr(page, "_follower_count_cache", cache)
                after = len(cache)
                if found or after != before:
                    _debug({"stage": "response_cache", "url": url[:160], "found": found, "cache_size": after, "sample_keys": list(cache.keys())[:10]})
            except Exception as e:
                _debug({"stage": "response_cache_error", "error": str(e)[:200]})

        try:
            page.on("response", lambda response: asyncio.create_task(handle_response(response)))
            _debug({"stage": "attach_cache_ok"})
        except Exception as e:
            _debug({"stage": "attach_cache_failed", "error": str(e)[:200]})




    def attach_profile_response_cache(self, page):
        """TikTokフィードAPIレスポンスからプロフィール紹介文をキャッシュする。プロフィールページは開かない。"""
        try:
            if getattr(page, "_profile_cache_attached", False):
                return
            setattr(page, "_profile_cache_attached", True)
            setattr(page, "_profile_text_cache", {})
        except Exception:
            return

        import asyncio

        def pick_uid(obj):
            if not isinstance(obj, dict):
                return ""
            for k in ["uniqueId", "unique_id", "id", "nickname"]:
                v = obj.get(k)
                if isinstance(v, str) and v:
                    return v.replace("@", "")
            return ""

        def pick_profile_text(obj):
            if not isinstance(obj, dict):
                return ""
            vals = []
            for k in ["signature", "bio", "desc", "description", "profile", "profileDesc"]:
                v = obj.get(k)
                if isinstance(v, str) and v.strip():
                    vals.append(v.strip())
            return " ".join(vals).strip()

        def walk(obj, cache, depth=0):
            if depth > 12 or obj is None:
                return 0
            found = 0
            if isinstance(obj, list):
                for x in obj:
                    found += walk(x, cache, depth + 1)
                return found
            if not isinstance(obj, dict):
                return 0

            author = obj.get("author") or obj.get("authorInfo") or obj.get("user") or {}
            if isinstance(author, dict):
                uid = pick_uid(author)
                txt = pick_profile_text(author)
                if uid and txt:
                    cache[uid] = txt
                    found += 1

            uid2 = pick_uid(obj)
            txt2 = pick_profile_text(obj)
            if uid2 and txt2:
                cache[uid2] = txt2
                found += 1

            for v in obj.values():
                if isinstance(v, (dict, list)):
                    found += walk(v, cache, depth + 1)
            return found

        async def handle_response(response):
            try:
                url = response.url or ""
                if "tiktok.com" not in url:
                    return
                if "/api/" not in url and "item_list" not in url and "recommend" not in url and "feed" not in url:
                    return
                try:
                    data = await response.json()
                except Exception:
                    return
                cache = getattr(page, "_profile_text_cache", {}) or {}
                walk(data, cache)
                setattr(page, "_profile_text_cache", cache)
            except Exception:
                return

        try:
            page.on("response", lambda response: asyncio.create_task(handle_response(response)))
        except Exception:
            pass




    async def detect_follower_count_from_feed(self, page, user_id=None, wait_sec: float = 1.5):
        """
        APIレスポンスキャッシュから、指定user_idに完全一致するフォロワー数だけ返す。
        DOM/hoverの汎用テキストは別アカウント混入の原因になるため使わない。

        cache が空のときは wait_sec 内で 100ms 間隔ポーリングして応答到着を待つ。
        動画 DOM 出現から API レスポンス到着までラグがあるケースを救う。
        """
        import asyncio
        try:
            self.attach_follower_response_cache(page)
        except Exception:
            pass

        uid = str(user_id or "").replace("@", "").strip()
        if not uid:
            return None, ""

        deadline = asyncio.get_event_loop().time() + max(0.0, wait_sec)
        while True:
            try:
                cache = getattr(page, "_follower_count_cache", {}) or {}
                if uid in cache:
                    return int(cache[uid]), "feed-api-cache"
            except Exception:
                pass
            if asyncio.get_event_loop().time() >= deadline:
                return None, ""
            await asyncio.sleep(0.1)

    async def detect_profile_text_from_feed(self, page, user_id=None, wait_sec: float = 1.5):
        """
        プロフィールページを開かず、指定user_idに完全一致する紹介文だけ返す。
        DOM上の汎用テキストは別アカウント混入の原因になるため使わない。

        cache が空のときは wait_sec 内で 100ms 間隔ポーリングして応答到着を待つ。
        """
        import asyncio
        try:
            self.attach_profile_response_cache(page)
        except Exception:
            pass

        uid = str(user_id or "").replace("@", "").strip()
        if not uid:
            return "", ""

        deadline = asyncio.get_event_loop().time() + max(0.0, wait_sec)
        while True:
            try:
                cache = getattr(page, "_profile_text_cache", {}) or {}
                if uid in cache:
                    return str(cache[uid] or ""), "feed-api-cache"
            except Exception:
                pass
            if asyncio.get_event_loop().time() >= deadline:
                return "", ""
            await asyncio.sleep(0.1)

    async def enrich_via_hover(self, page, user_id: str, hover_wait_sec: float = 1.5) -> dict:
        """@uid のリンクを hover して、ポップオーバーから follower/bio を抽出する。
        API レスポンスキャッシュが空のときのフォールバック経路。

        手順:
          1. 中央動画の近くにある `/@uid` リンクを位置スコアで特定
          2. mouse.move で hover(クリックはしない)
          3. ポップオーバー出現を 1.5 秒待つ
          4. hover で誘発された API レスポンスが cache に乗っていればそれを採用
          5. cache にもないときはポップオーバー DOM から regex で抽出
          6. マウスを動画外に戻して popover を閉じる
          7. 取得できた値は cache にも書き戻して再利用可能にする

        Returns: {"follower_count": int|None, "bio": str}
        """
        import asyncio
        uid_clean = str(user_id or "").replace("@", "").strip()
        result = {"follower_count": None, "bio": ""}
        if not uid_clean:
            return result

        # 1. @uid リンクの位置を特定
        try:
            link_pos = await page.evaluate(
                """(uid) => {
                  const visible = (el) => {
                    if (!el) return false;
                    const r = el.getBoundingClientRect();
                    const s = getComputedStyle(el);
                    return r.width > 16 && r.height > 16 &&
                           s.display !== 'none' && s.visibility !== 'hidden' &&
                           r.bottom > 0 && r.top < innerHeight && r.right > 0 && r.left < innerWidth;
                  };
                  const vids = Array.from(document.querySelectorAll('video'))
                    .filter(visible)
                    .map(v => ({el: v, rect: v.getBoundingClientRect()}))
                    .filter(x => x.rect.width > 120 && x.rect.height > 180);
                  if (!vids.length) return null;
                  vids.sort((a, b) => {
                    const dA = Math.abs((a.rect.left + a.rect.width/2) - innerWidth/2);
                    const dB = Math.abs((b.rect.left + b.rect.width/2) - innerWidth/2);
                    return dA - dB;
                  });
                  const vr = vids[0].rect;
                  const links = Array.from(document.querySelectorAll('a[href*="/@' + uid + '"]')).filter(visible);
                  if (!links.length) return null;
                  links.sort((a, b) => {
                    const ra = a.getBoundingClientRect();
                    const rb = b.getBoundingClientRect();
                    const da = Math.hypot(
                      (ra.left + ra.width/2) - (vr.left + vr.width/2),
                      (ra.top + ra.height/2) - (vr.top + vr.height/2)
                    );
                    const db = Math.hypot(
                      (rb.left + rb.width/2) - (vr.left + vr.width/2),
                      (rb.top + rb.height/2) - (vr.top + vr.height/2)
                    );
                    return da - db;
                  });
                  const link = links[0];
                  const r = link.getBoundingClientRect();
                  return { x: r.left + r.width/2, y: r.top + r.height/2 };
                }""",
                uid_clean,
            )
        except Exception:
            return result
        if not link_pos:
            return result

        # 2. hover
        try:
            await page.mouse.move(link_pos["x"], link_pos["y"], steps=8)
        except Exception:
            return result

        # 3. popover 出現待ち
        await asyncio.sleep(max(0.0, hover_wait_sec))

        # 4. hover で発火した API レスポンスが cache に届いているかも
        fc_from_cache = None
        bio_from_cache = ""
        try:
            fc_cache = getattr(page, "_follower_count_cache", {}) or {}
            if uid_clean in fc_cache:
                fc_from_cache = int(fc_cache[uid_clean])
        except Exception:
            pass
        try:
            pt_cache = getattr(page, "_profile_text_cache", {}) or {}
            if uid_clean in pt_cache:
                bio_from_cache = str(pt_cache[uid_clean] or "")
        except Exception:
            pass

        # 5. DOM ポップオーバーから抽出
        dom_data = {"follower_count": None, "bio": ""}
        try:
            dom_data = await page.evaluate(
                r"""() => {
                  const visible = (el) => {
                    if (!el) return false;
                    const r = el.getBoundingClientRect();
                    const s = getComputedStyle(el);
                    return r.width > 50 && r.height > 30 &&
                           s.display !== 'none' && s.visibility !== 'hidden';
                  };
                  // 1) 既知の data-e2e セレクタを試す
                  let popover = null;
                  const sels = [
                    '[data-e2e="user-card"]',
                    '[data-e2e="user-card-popup"]',
                    '[data-e2e="profile-card"]',
                    '[data-e2e*="user-card"]',
                    '[data-e2e*="profile-card"]',
                  ];
                  for (const sel of sels) {
                    for (const el of document.querySelectorAll(sel)) {
                      if (visible(el)) { popover = el; break; }
                    }
                    if (popover) break;
                  }
                  // 2) フォールバック: position:absolute/fixed で、フォロワー文字を含むサイズ
                  //    妥当な要素を popover とみなす
                  if (!popover) {
                    const all = Array.from(document.querySelectorAll('div'));
                    for (const el of all) {
                      if (!visible(el)) continue;
                      const s = getComputedStyle(el);
                      if (s.position !== 'absolute' && s.position !== 'fixed') continue;
                      const r = el.getBoundingClientRect();
                      if (r.width < 200 || r.width > 800) continue;
                      if (r.height < 80 || r.height > 600) continue;
                      const t = (el.textContent || '').slice(0, 600);
                      if (!/(フォロワー|Followers?)/.test(t)) continue;
                      // 動画 / メインフィードを誤検出しないように
                      if (el.querySelectorAll('video').length > 0) continue;
                      popover = el;
                      break;
                    }
                  }
                  if (!popover) return { follower_count: null, bio: '' };

                  const popText = (popover.innerText || popover.textContent || '').trim();

                  // フォロワー数 parse: "1,234 フォロワー" "1.2万 フォロワー" "1.5K Followers" 等
                  let follower_count = null;
                  const fmatch = popText.match(/([\d,，.]+)\s*([万KkMm億]?)\s*(?:フォロワー|Followers?)/);
                  if (fmatch) {
                    let num = parseFloat(fmatch[1].replace(/[,，]/g, ''));
                    const unit = fmatch[2] || '';
                    if (unit === '万') num *= 10000;
                    else if (unit === '億') num *= 100000000;
                    else if (unit.toLowerCase() === 'k') num *= 1000;
                    else if (unit.toLowerCase() === 'm') num *= 1000000;
                    if (!isNaN(num)) follower_count = Math.round(num);
                  }

                  // bio: stats ラベルを含まない、最長の素テキスト要素
                  let bio = '';
                  const cands = Array.from(popover.querySelectorAll('p, h2, h3, div, span'));
                  for (const el of cands) {
                    const t = (el.textContent || '').trim();
                    if (!t || t.length < 5 || t.length > 400) continue;
                    if (/フォロワー|Followers?|Following|フォロー中|いいね|Likes/.test(t)) continue;
                    if (t.startsWith('@')) continue;
                    if (t.length > bio.length) bio = t;
                  }
                  return { follower_count, bio };
                }"""
            )
        except Exception:
            pass

        # 6. マウスを動画から外して popover を閉じる
        try:
            await page.mouse.move(50, 50, steps=4)
        except Exception:
            pass

        # 7. cache 値と DOM 値をマージ(cache 値があれば優先、無ければ DOM 値)
        final_fc = fc_from_cache if fc_from_cache is not None else dom_data.get("follower_count")
        final_bio = bio_from_cache or dom_data.get("bio") or ""

        # 取得できたものは cache にも書き戻して、後段の repair 等で再利用可能に
        if final_fc is not None:
            try:
                cache = getattr(page, "_follower_count_cache", {}) or {}
                cache[uid_clean] = int(final_fc)
                setattr(page, "_follower_count_cache", cache)
            except Exception:
                pass
        if final_bio:
            try:
                cache = getattr(page, "_profile_text_cache", {}) or {}
                cache[uid_clean] = final_bio
                setattr(page, "_profile_text_cache", cache)
            except Exception:
                pass

        result["follower_count"] = int(final_fc) if final_fc is not None else None
        result["bio"] = final_bio
        return result

    async def screenshot_current(self, page: Page, unique_id: str) -> str:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = self.screenshot_dir / f"{ts}_{unique_id}.jpg"

        try:
            box = await page.evaluate(r"""
            () => {
              const vw = window.innerWidth, vh = window.innerHeight;
              const visible = (el) => {
                const r = el.getBoundingClientRect();
                const s = window.getComputedStyle(el);
                return r.width > 120 && r.height > 180 && s.display !== 'none' && s.visibility !== 'hidden' && r.bottom > 0 && r.top < vh;
              };
              const dist = (r) => Math.abs((r.left + r.width/2) - vw/2) + Math.abs((r.top + r.height/2) - vh/2);
              const videos = Array.from(document.querySelectorAll('video'))
                .filter(visible)
                .map(v => v.getBoundingClientRect())
                .sort((a,b) => dist(a) - dist(b));
              const r = videos[0];
              if (!r) return null;
              return {x: Math.max(0, r.left), y: Math.max(0, r.top), width: Math.min(r.width, vw - Math.max(0, r.left)), height: Math.min(r.height, vh - Math.max(0, r.top))};
            }
            """)
            if box and box["width"] > 80 and box["height"] > 80:
                await page.screenshot(path=str(path), type="jpeg", quality=70, clip=box)
                return str(path)
        except Exception:
            pass

        await page.screenshot(path=str(path), type="jpeg", quality=70, full_page=False)
        return str(path)


    async def mark_not_interested_current(self, page: Page) -> tuple[bool, str]:
        """
        現在表示中の投稿に対してTikTok側へ「興味がない」を1回返す。
        PCブラウザ版では三点メニューが上部バーの裏に隠れやすいため、
        動画右上の「・・・」付近を複数座標で試してから、メニュー内の
        「興味がない / Not interested」系の項目をクリックする。
        失敗しても例外で全体停止させず、(False, reason) を返す。
        """

        async def find_and_click_not_interested() -> tuple[bool, str]:
            try:
                result = await page.evaluate(r"""
                () => {
                  const visible = (el) => {
                    if (!el) return false;
                    const r = el.getBoundingClientRect();
                    const s = window.getComputedStyle(el);
                    return r.width > 2 && r.height > 2 &&
                           s.display !== 'none' && s.visibility !== 'hidden' &&
                           r.bottom > 0 && r.top < innerHeight && r.right > 0 && r.left < innerWidth;
                  };
                  const norm = (s) => String(s || '').replace(/\s+/g, '').toLowerCase();
                  const targets = [
                    '興味がない', '興味ありません', '興味なし', '興味ない',
                    'notinterested', 'not interested',
                    'この動画に興味がありません', 'この投稿に興味がありません'
                  ].map(norm);

                  const nodes = Array.from(document.querySelectorAll('button, [role="button"], [role="menuitem"], div, span, a'))
                    .filter(visible)
                    .map(el => {
                      const text = norm([el.innerText, el.textContent, el.getAttribute('aria-label'), el.getAttribute('title')].join(' '));
                      const r = el.getBoundingClientRect();
                      return {el, text, area: r.width * r.height, x: r.left + r.width / 2, y: r.top + r.height / 2};
                    })
                    .filter(x => x.text && targets.some(t => x.text.includes(t)))
                    .sort((a,b) => a.area - b.area);

                  for (const x of nodes) {
                    let el = x.el.closest('button, [role="button"], [role="menuitem"], a') || x.el;
                    try {
                      el.click();
                      return {ok: true, reason: 'clicked-not-interested-text', sample: x.text.slice(0, 120)};
                    } catch(e) {}
                  }
                  return {ok: false, reason: 'not-interested-control-not-found'};
                }
                """)
                if result and result.get("ok"):
                    await page.wait_for_timeout(800)
                    return True, str(result.get("reason", "clicked"))
                return False, str((result or {}).get("reason", "not-interested-control-not-found"))
            except Exception as e:
                return False, str(e)[:200]

        try:
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(150)
        except Exception:
            pass

        try:
            click_points = await page.evaluate(r"""
            () => {
              const vw = window.innerWidth, vh = window.innerHeight;
              const visible = (el) => {
                if (!el) return false;
                const r = el.getBoundingClientRect();
                const s = window.getComputedStyle(el);
                return r.width > 120 && r.height > 180 &&
                       s.display !== 'none' && s.visibility !== 'hidden' &&
                       r.bottom > 0 && r.top < vh && r.right > 0 && r.left < vw;
              };
              const dist = (r) => Math.abs((r.left + r.width/2) - vw/2) + Math.abs((r.top + r.height/2) - vh/2);
              const videos = Array.from(document.querySelectorAll('video'))
                .filter(visible)
                .map(v => ({r: v.getBoundingClientRect()}))
                .sort((a,b) => dist(a.r) - dist(b.r));
              const r = videos[0]?.r;
              if (!r) return null;
              const clamp = (x, y, label) => ({
                x: Math.max(8, Math.min(vw - 8, x)),
                y: Math.max(8, Math.min(vh - 8, y)),
                label
              });
              return [
                clamp(r.right - 54, r.top + 50, 'video-right-minus-54-top50'),
                clamp(r.right - 70, r.top + 50, 'video-right-minus-70-top50'),
                clamp(r.right - 88, r.top + 50, 'video-right-minus-88-top50'),
                clamp(r.right - 54, r.top + 70, 'video-right-minus-54-top70'),
                clamp(r.right - 70, r.top + 70, 'video-right-minus-70-top70'),
                clamp(r.right - 105, r.top + 55, 'video-right-minus-105-top55')
              ];
            }
            """)
        except Exception:
            click_points = None

        if not click_points:
            return False, "video-not-found"

        last_reason = "not-interested-control-not-found"
        for pt in click_points:
            try:
                await page.keyboard.press("Escape")
                await page.wait_for_timeout(120)
                await page.mouse.click(float(pt["x"]), float(pt["y"]), button="left")
                await page.wait_for_timeout(650)

                ok, reason = await find_and_click_not_interested()
                if ok:
                    return True, f"{reason}:{pt.get('label', 'unknown')}"
                last_reason = f"{reason}:{pt.get('label', 'unknown')}"
            except Exception as e:
                last_reason = f"click-failed:{pt.get('label', 'unknown')}:{str(e)[:120]}"

        try:
            await page.keyboard.press("Escape")
        except Exception:
            pass
        return False, last_reason


    async def next_post(self, page: Page):
        # stealth 化: ArrowDown ではなく CDP マウスホイール(失敗時 chevron クリック、
        # それも失敗時のみ ArrowDown)を使う。probe.py で 60/60 完走済みの方式。
        from ._stealth import human_swipe
        await human_swipe(page)
