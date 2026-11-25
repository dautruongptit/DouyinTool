"""Douyin: nhận dạng link kênh, lấy danh sách video bằng Chrome thật, tải video + thumbnail.
Không chứa giao diện: dùng chung cho bản máy tính (Tkinter) và bản web trên server."""
import json
import re
import time
from datetime import datetime
from pathlib import Path

from .common import Stopped, safe, save_png

REFERER = "https://www.douyin.com/"

def norm_url(u):
    if u.startswith("//"):
        u = "https:" + u
    return u.replace("http://", "https://", 1)

def pick_video_url(aweme):
    v = aweme.get("video") or {}
    best = None
    for br in v.get("bit_rate") or []:
        urls = (br.get("play_addr") or {}).get("url_list") or []
        if urls and (best is None or br.get("bit_rate", 0) > best[0]):
            best = (br.get("bit_rate", 0), urls[0])
    if best:
        return norm_url(best[1])
    urls = (v.get("play_addr") or {}).get("url_list") or []
    return norm_url(urls[0]) if urls else None

def thumb_urls(aweme):
    """Link ảnh thumbnail (ảnh minh hoạ tác giả đặt, như hiện trên trang kênh), theo thứ tự ưu tiên.
    cover_original_scale = ảnh thumbnail bản gốc, đủ khung; cover = bản hiện trên lưới kênh.
    origin_cover/dynamic_cover là khung hình cắt từ video -> chỉ dùng khi không có ảnh nào khác."""
    v = aweme.get("video") or {}
    out = []
    for key in ("cover_original_scale", "cover", "origin_cover"):
        urls = [norm_url(u) for u in ((v.get(key) or {}).get("url_list") or [])]
        urls.sort(key=lambda u: 0 if "jpeg" in u or ".jpg" in u else 1)  # ưu tiên JPEG (dễ đổi sang PNG)
        out += [u for u in urls if u not in out]
    return out

SEC_UID_RE = re.compile(r"MS4wLjAB[0-9A-Za-z_\-]+")

def parse_channel_link(text):
    """Nhận link/đoạn chữ chia sẻ bất kỳ, trả về (link_kênh_sạch hoặc None, link_rút_gọn hoặc None).
    Ví dụ: https://www.douyin.com/user/MS4w...?from_tab_name=main&vid=771...  -> https://www.douyin.com/user/MS4w..."""
    text = (text or "").strip()
    m = SEC_UID_RE.search(text)
    if m:
        return f"https://www.douyin.com/user/{m.group(0)}", None
    m = re.search(r"https?://v\.douyin\.com/[0-9A-Za-z_\-]+/?", text)
    if m:
        return None, m.group(0)
    return None, None

def resolve_short(short_url):
    """Mở link v.douyin.com để lấy link thật, rồi tách sec_uid."""
    import requests
    r = requests.get(short_url, allow_redirects=True, timeout=15,
                     headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120 Safari/537.36"})
    hops = [h.headers.get("Location", "") for h in r.history] + [r.url]
    for u in hops:
        m = SEC_UID_RE.search(u or "")
        if m:
            return f"https://www.douyin.com/user/{m.group(0)}"
    if any("/video/" in (u or "") for u in hops):
        raise RuntimeError("Đây là link của MỘT video, không phải link kênh. Mở video đó, bấm vào tên tác giả "
                           "để vào trang kênh rồi copy link trang kênh.")
    raise RuntimeError("Không tìm thấy mã kênh (sec_uid) trong link rút gọn này.")

def video_name(a):
    date = datetime.fromtimestamp(a.get("create_time", 0)).strftime("%Y%m%d")
    return f"{date}_{a['aweme_id']}_{safe(a.get('desc'))}"

def is_downloaded(out, a):
    p = Path(out).expanduser()
    return any(f.stat().st_size > 0 for f in p.glob(f"*_{a['aweme_id']}_*.mp4")) if p.is_dir() else False

def download_file(session, url, dest, stop, retries=3):
    part = dest.with_suffix(dest.suffix + ".part")
    last_err = None
    for attempt in range(1, retries + 1):
        if stop.is_set():
            raise Stopped()
        try:
            with session.get(url, stream=True, timeout=(15, 60)) as r:
                if r.status_code != 200:
                    last_err = f"HTTP {r.status_code}"
                    time.sleep(2 * attempt)
                    continue
                with open(part, "wb") as f:
                    for chunk in r.iter_content(chunk_size=1024 * 256):
                        if stop.is_set():
                            raise Stopped()
                        if chunk:
                            f.write(chunk)
            part.replace(dest)
            return True, None
        except Stopped:
            if part.exists():
                part.unlink()
            raise
        except Exception as e:
            last_err = str(e)
            time.sleep(2 * attempt)
    if part.exists():
        part.unlink()
    return False, last_err

SCROLL_JS = """() => {
  // Cuộn mọi khung có thanh cuộn xuống đáy (Douyin để danh sách video trong một khung cuộn riêng)
  let n = 0;
  for (const el of [document.scrollingElement, ...document.querySelectorAll('*')]) {
    if (!el) continue;
    const st = getComputedStyle(el);
    if (el === document.scrollingElement || /(auto|scroll)/.test(st.overflowY)) {
      if (el.scrollHeight > el.clientHeight + 50) { el.scrollTop = el.scrollHeight; n++; }
    }
  }
  window.scrollTo(0, document.body.scrollHeight);
  return n;
}"""

# Khung "Log in to Douyin" (đăng nhập bằng QR/SĐT) hay bật lên che trang. Tìm nút X và bấm.
CLOSE_LOGIN_JS = """() => {
  const vis = el => { if (!el) return false; const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const sels = ['.dy-account-close', '[class*="dy-account-close"]', '[data-e2e="login-close"]',
                '#login-panel-new [class*="close"]', '[id^="login-pa"] [class*="close"]',
                '[class*="login-panel"] [class*="close"]', '[class*="login"] [class*="close"]'];
  for (const s of sels) {
    const el = document.querySelector(s);
    if (vis(el)) { el.click(); return 'sel|' + s; }
  }
  const panel = document.querySelector('#login-panel-new, [id^="login-pa"], [class*="login-panel"]');
  if (!vis(panel)) return '';
  // Không có mã nhận diện nút X: tìm "thẻ" đăng nhập (khối lớn nhất) rồi bấm phần tử nhỏ ở góc phải-trên của nó
  let card = null, best = 0;
  for (const el of panel.querySelectorAll('*')) {
    const r = el.getBoundingClientRect();
    if (r.width >= 400 && r.width <= 1100 && r.height >= 300 && r.height <= 800 && r.width * r.height > best) { card = el; best = r.width * r.height; }
  }
  if (card) {
    const c = card.getBoundingClientRect();
    const cands = [];
    for (const el of card.querySelectorAll('*')) {
      const r = el.getBoundingClientRect();
      if (r.width >= 10 && r.width <= 70 && r.height >= 10 && r.height <= 70 && r.right > c.right - 90 && r.top < c.top + 90) cands.push(el);
    }
    const nm = e => e.tagName + '.' + String(e.className && e.className.baseVal !== undefined ? e.className.baseVal : e.className).slice(0, 40);
    const d = 'card ' + Math.round(c.width) + 'x' + Math.round(c.height) + ' ứng viên: ' + cands.slice(0, 5).map(nm).join(' , ');
    if (cands.length) { cands[0].click(); return 'geo|' + d; }
    return 'esc|' + d + ' | HTML: ' + card.outerHTML.slice(0, 300).replace(/\\s+/g, ' ');
  }
  return 'esc|không thấy thẻ; HTML: ' + panel.outerHTML.slice(0, 300).replace(/\\s+/g, ' ');
}"""

def close_login_popup(page, log=None, state=None):
    """Nếu đang có khung đăng nhập Douyin (đang hiện) thì đóng (bấm X). Trả về True nếu thấy khung."""
    try:
        raw = page.evaluate(CLOSE_LOGIN_JS)
        kind, _, dbg = (raw or "").partition("|")
        if kind == "esc":
            page.keyboard.press("Escape")
        if kind:
            if state is None:
                state = {}
            n = state["n"] = state.get("n", 0) + 1
            if log and (n == 1 or n % 20 == 0):
                log(f"Thấy khung đăng nhập Douyin (lần {n}), cách đóng: {kind}. {dbg[:420]}")
            return True
    except Exception:
        pass
    return False

# ---- Lấy danh sách trực tiếp từ trang kênh (khi Douyin không trả dữ liệu API cho Chromium tự động) ----
# Trang kênh vẫn hiện lưới video dù chưa đăng nhập. Đọc link /video/<id>, tiêu đề và ảnh bìa từ lưới đó.
GRID_JS = r"""() => {
  const rows = [];
  // Ưu tiên khung bài đăng của kênh, tránh lẫn video gợi ý của kênh khác
  const root = document.querySelector('[data-e2e="user-post-list"]') || document;
  for (const a of root.querySelectorAll('a[href*="/video/"]')) {
    const href = a.getAttribute('href') || '';
    const id = (href.split('/video/')[1] || '').split(/[^0-9]/)[0];
    if (!id) continue;
    const img = a.querySelector('img');
    let cover = img ? (img.currentSrc || img.src || '') : '';
    if (cover.startsWith('data:')) cover = '';
    const box = a.closest('li') || a;
    const lines = (box.innerText || '').split('\n').map(s => s.trim()).filter(s => s && !/^[0-9.,]+[KkWw万]?$/.test(s));
    lines.sort((x, y) => y.length - x.length);
    rows.push({id: id, cover: cover, title: lines[0] || ''});
  }
  return rows;
}"""

# Trên trang một video: lấy link file mp4 từ thẻ <video>.
VIDEO_SRC_JS = r"""() => {
  const urls = [];
  for (const v of document.querySelectorAll('video')) {
    if (v.currentSrc) urls.push(v.currentSrc);
    if (v.src) urls.push(v.src);
    for (const s of v.querySelectorAll('source')) if (s.src) urls.push(s.src);
  }
  return urls.filter(u => u.startsWith('http'));
}"""


def dom_to_aweme(row):
    """Chuyển 1 ô trên lưới thành dict giống aweme của API. ID video của Douyin có 32 bit cao là mốc thời gian (giây)."""
    vid = row["id"]
    ts = int(vid) >> 32
    return {"aweme_id": vid, "desc": row.get("title", ""), "create_time": ts if 1_400_000_000 < ts < 4_000_000_000 else 0,
            "video": {"cover": {"url_list": [row["cover"]] if row.get("cover") else []}}, "_dom": True}


def scrape_grid(page, log, stop, limit, total, prog, popup):
    """Cuộn trang kênh và đọc lưới video. Trả về list dict {id, cover, title}."""
    found = {}
    idle = 0
    page.mouse.move(640, 500)
    for _ in range(120):
        if stop.is_set():
            raise Stopped()
        close_login_popup(page, log, popup)
        try:
            rows = page.evaluate(GRID_JS)
        except Exception:
            rows = []
        before = len(found)
        for r in rows:
            found.setdefault(r["id"], r)
        n = len(found)
        if n != before:
            log(f"Đã đọc {n}{('/' + str(total)) if total else ''} video từ trang kênh...")
            if total:
                prog(n, total)
            idle = 0
        else:
            idle += 1
        if (limit and n >= limit) or (total and n >= total) or idle >= 6:
            break
        try:
            page.evaluate(SCROLL_JS)
        except Exception:
            pass
        page.mouse.wheel(0, 3000)
        page.keyboard.press("End")
        page.wait_for_timeout(1500)
    return list(found.values())


def resolve_dom_videos(need, browser, log, prog, stop):
    """Mở từng trang video bằng trình duyệt để lấy link mp4, gắn vào item (item['video']['play_addr'])."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise RuntimeError("Thiếu thư viện. Chạy: python -m pip install playwright requests")
    log(f"Lấy link tải của {len(need)} video bằng trình duyệt (danh sách đọc từ trang nên chưa có link)...")
    hidden = browser.get("hidden", True)
    args = ["--disable-backgrounding-occluded-windows", "--disable-renderer-backgrounding",
            "--disable-background-timer-throttling"]
    if hidden:
        args.append("--window-position=-32000,-32000")
    popup = {"n": 0}
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            browser["profile"], channel=browser.get("channel"), headless=False,
            viewport={"width": 1280, "height": 900}, args=args)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        ok = 0
        for i, a in enumerate(need, 1):
            if stop.is_set():
                ctx.close()
                raise Stopped()
            vid = a["aweme_id"]
            url = None
            try:
                page.goto(f"https://www.douyin.com/video/{vid}", wait_until="domcontentloaded")
                t0 = time.time()
                while not url and time.time() - t0 < 20:
                    page.wait_for_timeout(700)
                    close_login_popup(page, None, popup)
                    srcs = page.evaluate(VIDEO_SRC_JS)
                    mp4 = [u for u in srcs if "video_mp4" in u or ".mp4" in u]
                    url = (mp4 or srcs or [None])[0]
            except Exception as e:
                log(f"   [{i}/{len(need)}] lỗi mở trang {vid}: {e}")
            if url:
                a["video"]["play_addr"] = {"url_list": [url]}
                ok += 1
            else:
                log(f"   [{i}/{len(need)}] không thấy link video trên trang {vid}")
            prog(i, len(need))
        ctx.close()
    log(f"Đã lấy được link của {ok}/{len(need)} video.")


def open_for_login(cfg, log, prog, wait_user, stop):
    """Mở Chrome (cùng profile với lúc lấy danh sách) tới douyin.com để người dùng tự đăng nhập
    (quét mã QR). Đăng nhập được lưu trong profile, các lần sau không phải làm lại.
    Chờ đến khi người dùng bấm Tiếp tục (wait_user) hoặc bấm Dừng."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise RuntimeError("Thiếu thư viện. Chạy: python -m pip install playwright requests")
    log("Đang mở Chrome tới douyin.com ...")
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            cfg["profile"], channel=cfg["channel"], headless=False,
            viewport={"width": 1280, "height": 900},
            args=["--disable-backgrounding-occluded-windows", "--disable-renderer-backgrounding",
                  "--disable-background-timer-throttling"])
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto("https://www.douyin.com/", wait_until="domcontentloaded")
        log("Chrome đã mở douyin.com. Mở 'Màn hình Chrome', đăng nhập (quét mã QR bằng app Douyin), "
            "xong bấm 'Tiếp tục'. Đăng nhập được lưu cho các lần sau.")

        def ready():
            page.wait_for_timeout(200)  # cho Playwright xử lý sự kiện của trang trong lúc chờ
            return False
        wait_user(ready)
        ctx.close()
    if stop.is_set():
        raise Stopped()
    log("Đã đóng Chrome. Đăng nhập (nếu đã làm) được lưu trong profile.")
    return "ok"


def collect_list(cfg, log, prog, wait_user, stop):
    """Bước 1: dùng Chrome lấy danh sách video + cookie. Trả về dict(items, cookies, ua, total)."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise RuntimeError("Thiếu thư viện. Chạy: python -m pip install playwright requests")

    if cfg.get("short"):
        log(f"Đang mở link rút gọn {cfg['short']} ...")
        cfg["url"] = resolve_short(cfg["short"])
        log(f"Link kênh: {cfg['url']}")
    out = Path(cfg["out"]).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    limit = cfg["limit"]
    collected = {}
    info = {"total": None, "has_more": True, "posts": []}
    popup = {"n": 0}

    hidden = cfg.get("hidden", True)
    log("Đang mở Chrome ở chế độ ẩn..." if hidden else "Đang mở Chrome...")
    with sync_playwright() as p:
        # Chế độ ẩn: vẫn là Chrome thật (Douyin không chặn), chỉ đặt cửa sổ ra ngoài màn hình.
        extra = ["--window-position=-32000,-32000"] if hidden else []
        # không cho Chrome "ngủ" khi cửa sổ bị che/ẩn, nếu không trang sẽ không tải thêm video khi cuộn
        extra += ["--disable-backgrounding-occluded-windows", "--disable-renderer-backgrounding",
                  "--disable-background-timer-throttling"]
        ctx = p.chromium.launch_persistent_context(
            cfg["profile"], channel=cfg["channel"], headless=False,
            viewport={"width": 1280, "height": 900}, args=extra)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        def show_window():
            try:
                cdp = ctx.new_cdp_session(page)
                wid = cdp.send("Browser.getWindowForTarget")["windowId"]
                cdp.send("Browser.setWindowBounds", {"windowId": wid, "bounds": {"windowState": "normal"}})
                cdp.send("Browser.setWindowBounds",
                         {"windowId": wid, "bounds": {"left": 80, "top": 40, "width": 1280, "height": 900}})
                page.bring_to_front()
            except Exception as e:
                log(f"(Không đưa được cửa sổ Chrome ra giữa: {e})")

        def on_response(resp):
            u = resp.url
            if "aweme/post" in u:
                try:
                    data = resp.json()
                except Exception:
                    try:
                        body = resp.body()
                        snip = body[:80].decode("utf-8", "replace").replace("\n", " ")
                        info["posts"].append(f"HTTP {resp.status}, thân {len(body)} byte, không phải JSON: '{snip}'")
                    except Exception:
                        info["posts"].append(f"HTTP {resp.status}, không đọc được thân phản hồi")
                    return
                lst = data.get("aweme_list") or []
                info["posts"].append(f"HTTP {resp.status}, {len(lst)} video, status_code={data.get('status_code')}, "
                                     f"msg={str(data.get('status_msg') or '')[:60]}")
                for a in lst:
                    if a.get("aweme_id"):
                        collected[a["aweme_id"]] = a
                info["has_more"] = bool(data.get("has_more", 1))
            elif "user/profile/other" in u:
                try:
                    cnt = (resp.json().get("user") or {}).get("aweme_count")
                    if cnt:
                        info["total"] = int(cnt)
                except Exception:
                    pass

        page.on("response", on_response)
        page.goto(cfg["url"], wait_until="domcontentloaded")
        # Tự chờ danh sách video xuất hiện (tối đa 25 giây)
        t0 = time.time()
        closed_at, reloads = None, 0
        while not collected and time.time() - t0 < 25:
            if stop.is_set():
                ctx.close()
                raise Stopped()
            page.wait_for_timeout(500)
            if close_login_popup(page, log, popup):
                closed_at = closed_at or time.time()
            if closed_at and not collected and time.time() - closed_at > 3 and reloads < 2:
                # đã đóng khung đăng nhập mà vẫn chưa có danh sách -> tải lại trang để lấy lại
                log("Đã đóng khung đăng nhập nhưng chưa có danh sách, tải lại trang để lấy lại...")
                page.reload(wait_until="domcontentloaded")
                reloads, closed_at, t0 = reloads + 1, None, time.time()
            if time.time() - t0 > 8 and not collected:
                page.mouse.wheel(0, 1500)  # đôi khi phải cuộn nhẹ Douyin mới gọi danh sách
        if collected:
            log(f"Đã tự nhận danh sách video ({len(collected)} video đầu tiên), bắt đầu cuộn...")
        else:
            try:
                has_cap = page.evaluate("!!document.querySelector('#captcha_container, .captcha_verify_container, [class*=captcha]')")
                log(f"[Chẩn đoán] Trang: {page.url[:90]} | Tiêu đề: {page.title()[:50]} | "
                    f"Khung đăng nhập thấy {popup['n']} lần | Captcha: {'có' if has_cap else 'không'}")
                dom = page.evaluate("""() => ({
                    videos: document.querySelectorAll('a[href*="/video/"]').length,
                    renderData: !!document.querySelector('#RENDER_DATA'),
                    webdriver: navigator.webdriver, lang: navigator.language, ua: navigator.userAgent.slice(0, 90)})""")
                log(f"[Chẩn đoán] Trong trang: {dom}")
                log("[Chẩn đoán] Phản hồi aweme/post: " + (" ; ".join(info["posts"][:5]) or "KHÔNG có phản hồi nào"))
            except Exception as e:
                log(f"[Chẩn đoán] lỗi: {e}")
            # Không cần đăng nhập: trang kênh vẫn hiện lưới video -> đọc danh sách thẳng từ trang
            log("Douyin không trả danh sách qua API, thử đọc danh sách trực tiếp từ trang kênh (không cần đăng nhập)...")
            try:
                rows = scrape_grid(page, log, stop, limit, info["total"], prog, popup)
            except Stopped:
                ctx.close()
                raise
            for r in rows:
                collected.setdefault(r["id"], dom_to_aweme(r))  # không đè lên dữ liệu API (API có sẵn link tải)

            def has_api():
                return any(not a.get("_dom") for a in collected.values())

            enough = (limit and len(collected) >= limit) or (info["total"] and len(collected) >= info["total"])
            if not enough and not has_api():
                # Thiếu video thì KHÔNG coi là xong: giữ Chrome mở để người dùng đăng nhập rồi lấy tiếp
                log(f"Cảnh báo: mới đọc được {len(collected)}/{info['total'] or '?'} video vì Douyin không trả phần còn lại. "
                    "Đăng nhập trong cửa sổ Chrome rồi bấm tiếp tục để lấy đủ, hoặc bấm tiếp tục luôn để dùng "
                    "danh sách thiếu này.")
                if hidden:
                    show_window()

                def ready():
                    page.wait_for_timeout(200)  # cho Playwright nhận phản hồi mạng
                    return has_api()
                wait_user(ready)
                if not stop.is_set() and not has_api():
                    log("Tải lại trang kênh để lấy tiếp danh sách...")
                    try:
                        page.goto(cfg["url"], wait_until="domcontentloaded")
                        t1 = time.time()
                        while not has_api() and not stop.is_set() and time.time() - t1 < 15:
                            page.wait_for_timeout(500)
                    except Exception as e:
                        log(f"Không tải lại được trang: {e}")
            if not has_api():
                info["has_more"] = False  # chỉ có danh sách đọc từ trang, cuộn tiếp cũng không ra thêm
        if stop.is_set():
            ctx.close()
            raise Stopped()

        def tot():
            return f"/{info['total']}" if info["total"] else ""

        page.mouse.move(640, 500)  # đặt chuột giữa danh sách để cuộn đúng khung
        idle, last, shown_win = 0, len(collected), False
        while True:
            if stop.is_set():
                ctx.close()
                raise Stopped()
            n = len(collected)
            if limit and n >= limit:
                break
            if not info["has_more"] or (info["total"] and n >= info["total"]):
                break  # Douyin báo đã hết video
            close_login_popup(page, log, popup)  # khung đăng nhập có thể bật lại giữa chừng và chặn cuộn
            try:
                page.evaluate(SCROLL_JS)
            except Exception:
                pass
            page.mouse.wheel(0, 4000)
            page.keyboard.press("End")
            page.wait_for_timeout(1500)  # chờ bằng Playwright để nó kịp nhận dữ liệu mạng
            n = len(collected)
            if n != last:
                log(f"Đã lấy {n}{tot()} video...")
                if info["total"]:
                    prog(n, info["total"])
                idle, last = 0, n
            else:
                idle += 1
                if idle == 6 and hidden and not shown_win:
                    # ẩn mà không cuộn được -> hiện cửa sổ ra thử tiếp
                    log("Chưa lấy thêm được video ở chế độ ẩn, đưa cửa sổ Chrome ra để thử tiếp...")
                    show_window()
                    page.mouse.move(640, 500)
                    shown_win, idle = True, 0
                elif idle >= 8:
                    break
        ua = page.evaluate("navigator.userAgent")
        cookies = ctx.cookies()
        ctx.close()

    items = sorted(collected.values(), key=lambda a: a.get("create_time", 0), reverse=True)
    if limit:
        items = items[:limit]
    (out / "links.txt").write_text(
        "\n".join(f"https://www.douyin.com/video/{a['aweme_id']}" for a in items), encoding="utf-8")
    msg = f"Lấy danh sách xong: {len(items)}{tot()} video. Chrome đã đóng."
    if info["total"] and len(items) < info["total"] and not limit:
        msg += (f" (Kênh báo {info['total']}, chênh {info['total'] - len(items)} video: có thể là video ẩn/riêng tư/đã gỡ, "
                "hoặc đã tải về từ trước. Bấm 'Lấy danh sách' lại nếu muốn thử tiếp.)")
    log(msg)
    return dict(items=items, cookies=cookies, ua=ua, total=info["total"],
                browser=dict(profile=cfg["profile"], channel=cfg["channel"], hidden=hidden))

def download_items(cfg, res, log, prog, stop):
    """Bước 2: tải video + thumbnail từ danh sách đã lấy."""
    try:
        import requests
    except ImportError:
        raise RuntimeError("Thiếu thư viện. Chạy: python -m pip install requests")
    out = Path(cfg["out"]).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    items, cookies, ua = res["items"], res["cookies"], res["ua"]
    log(f"Bắt đầu tải {len(items)} video vào {out}")

    need = [a for a in items if a.get("_dom") and not pick_video_url(a) and not is_downloaded(out, a)]
    if need:
        if res.get("browser"):
            resolve_dom_videos(need, res["browser"], log, prog, stop)
        else:
            log("Thiếu thông tin trình duyệt để lấy link tải. Hãy bấm 'Lấy danh sách' lại.")

    s = requests.Session()
    s.headers.update({"User-Agent": ua, "Referer": REFERER})
    for c in cookies:
        s.cookies.set(c["name"], c["value"], domain=c.get("domain"), path=c.get("path", "/"))

    thumb_dir = out / "thumbnails"
    if cfg.get("thumbs", True):
        thumb_dir.mkdir(exist_ok=True)
    ok = fail = skipped = 0
    failed_ids = []
    prog(0, max(1, len(items)))
    for i, a in enumerate(items, 1):
        if stop.is_set():
            raise Stopped()
        vid = a["aweme_id"]
        name = video_name(a)
        mp4 = out / f"{name}.mp4"
        if cfg.get("thumbs", True):
            thumb = thumb_dir / f"{name}.png"
            old = out / f"{name}.cover.jpg"  # file của bản cũ (khung hình video): xoá
            if not thumb.exists():
                tmp_jpg = thumb_dir / f"{name}.tmp.jpg"
                done_thumb = False
                for cu in thumb_urls(a):
                    try:
                        if download_file(s, cu, tmp_jpg, stop, retries=2)[0]:
                            save_png(tmp_jpg, thumb)
                            done_thumb = True
                            break
                    except Stopped:
                        raise
                    except Exception:
                        continue  # ảnh định dạng lạ -> thử link kế tiếp
                    finally:
                        if tmp_jpg.exists():
                            tmp_jpg.unlink()
                if not done_thumb:
                    log(f"   không tải được thumbnail cho {vid}")
            if old.exists():
                old.unlink()
        if mp4.exists() and mp4.stat().st_size > 0:
            log(f"[{i}/{len(items)}] bỏ qua (đã có): {mp4.name}")
            skipped += 1
        else:
            url = pick_video_url(a)
            if not url:
                log(f"[{i}/{len(items)}] không có link video: {vid}")
                fail += 1
                failed_ids.append(vid)
            else:
                good, err = download_file(s, url, mp4, stop)
                if good:
                    (out / f"{name}.json").write_text(
                        json.dumps({"id": vid, "desc": a.get("desc"), "create_time": a.get("create_time")},
                                   ensure_ascii=False, indent=2), encoding="utf-8")
                    log(f"[{i}/{len(items)}] đã tải: {mp4.name}")
                    ok += 1
                else:
                    log(f"[{i}/{len(items)}] LỖI ({err}): {vid}")
                    fail += 1
                    failed_ids.append(vid)
                time.sleep(cfg["sleep"])
        prog(i, len(items))

    summary = f"Tải xong. Tải mới: {ok} | Đã có từ trước: {skipped} | Lỗi: {fail}"
    log("XONG. " + summary)
    if failed_ids:
        (out / "failed_ids.txt").write_text("\n".join(failed_ids), encoding="utf-8")
        log("Có video lỗi (failed_ids.txt). Bấm tải lại để thử tiếp, file đã tải sẽ được bỏ qua.")
    return summary
